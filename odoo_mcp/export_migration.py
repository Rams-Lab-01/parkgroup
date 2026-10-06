"""Migration-grade export: pgre.odoo.com -> a NEW database.

Why this file exists separately from ``export_data.py``
-------------------------------------------------------
``export_data.py`` produces flat, human-facing CSV/XLSX for analysis.  This
script produces a **dependency-ordered, reference-preserving** dump intended
to be loaded into a fresh database.  Two things make it different:

1. **Every record carries ``old_id`` plus natural keys** (account code, journal
   code, partner VAT, etc.) so the importer can resolve references against the
   new database instead of relying on numeric ids, which will not match.
2. **Models are exported in dependency order** (``LOAD_ORDER``), so parents
   exist before children: companies before journals before accounts before
   moves before payments.

READ THIS BEFORE MIGRATING BY CSV
---------------------------------
For "move everything to a new database", a CSV round-trip is the *wrong* tool
and will lose data that cannot be recovered by any import script:

* reconciliation history (``account.partial.reconcile`` /
  ``account.full.reconcile``) â€” invoice<->payment matching
* sequence positions (new invoices may collide with old numbers)
* attachments and binary fields stored on disk
* analytic distribution, multi-currency revaluation, fiscal year locks
* computed fields, follow-ups, chatter

The **lossless route** on Odoo.sh is the platform's own database **Backup**
(``pgre.odoo.com`` is an Odoo.sh branch): take a ``.dump`` in Odoo.sh, then
restore it into the destination (a new Odoo.sh branch, a self-hosted Odoo, or
an Odoo Online trial via "Restore"). That preserves everything above.

Use this CSV exporter for the cases the dump cannot express:
* a **clean rebuild** with only some companies (your 7 entities), or
* a **subset**, e.g. only one legal entity, or only FY2025+, or
* an **audit/analysis copy** kept outside Odoo.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import accounting as _accounting
import fieldplan
from accounting import (
    INVOICE_FIELDS,
    MOVE_LINE_FIELDS,
    PAYMENT_FIELDS,
    classify_move,
    classify_payment,
    domain_for_move_bucket,
    domain_for_move_lines,
    domain_for_payment_bucket,
)
from pgre_client import OdooAuthError, OdooClient, OdooError

log = logging.getLogger("pgre.migration")

# --------------------------------------------------------------------------- #
# Dependency-ordered model list
# --------------------------------------------------------------------------- #
# Order matters: a record must exist before anything referencing it.
# Field tuples here are **fallbacks only** - ``build()`` replaces them with the
# live schema from ``fieldplan`` so custom fields are always captured.
#   (key, model, label, fallback fields)
LOAD_ORDER: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("companies", "res.company", "Legal entities / companies", (
        "id", "name", "partner_id", "currency_id", "parent_id",
        "country_id", "vat", "street", "city", "zip", "email", "phone")),
    ("currencies", "res.currency", "Currencies", (
        "id", "name", "symbol", "rounding", "decimal_places", "active", "position")),
    ("countries", "res.country", "Countries", (
        "id", "name", "code")),
    ("journals", "account.journal", "Journals (sales/purchase/bank/cash/general)", (
        "id", "code", "name", "type", "company_id", "currency_id",
        "bank_account_id", "default_account_id", "active")),
    ("accounts", "account.account", "Chart of accounts", (
        "id", "code", "name", "account_type", "internal_group", "reconcile",
        "currency_id")),
    ("taxes", "account.tax", "Taxes", (
        "id", "name", "amount", "amount_type", "tax_group_id", "company_id",
        "price_include_override", "active")),
    ("payment_terms", "account.payment.term", "Payment terms", (
        "id", "name", "note", "company_id", "active")),
    ("partners", "res.partner", "Customers, vendors, employees", (
        "id", "name", "ref", "email", "phone", "mobile", "vat",
        "country_id", "company_id", "parent_id", "customer_rank",
        "supplier_rank", "is_company", "active", "type")),
    ("products", "product.product", "Products / services (properties)", (
        "id", "name", "default_code", "type", "list_price", "standard_price",
        "company_id", "active")),
    ("users", "res.users", "Users (for reference / authorship)", (
        "id", "name", "login", "email", "company_id", "partner_id", "active")),
    ("analytic_accounts", "account.analytic.account", "Analytic accounts / cost centres", (
        "id", "name", "code", "company_id", "partner_id", "active")),
    ("fiscal_positions", "account.fiscal.position", "Fiscal positions", (
        "id", "name", "company_id", "auto_apply", "country_id")),
    # ---- financial documents
    ("invoices", "account.move", "Customer invoices", INVOICE_FIELDS),
    ("bills", "account.move", "Vendor bills", INVOICE_FIELDS),
    ("customer_refunds", "account.move", "Customer credit notes / refunds", INVOICE_FIELDS),
    ("vendor_refunds", "account.move", "Vendor credit notes", INVOICE_FIELDS),
    ("receipts", "account.move", "Sales + purchase receipts", INVOICE_FIELDS),
    ("journal_entries", "account.move", "Miscellaneous journal entries", INVOICE_FIELDS),
    ("payments", "account.payment", "Customer + vendor payments", PAYMENT_FIELDS),
    # ---- GL detail last: it references moves and accounts
    ("move_lines", "account.move.line", "All journal entry lines (GL)", MOVE_LINE_FIELDS),
]

#: Base (unfiltered) domain for each single-bucket financial dataset.
FINANCIAL_DOMAINS: dict[str, list[Any]] = {
    "invoices": domain_for_move_bucket("customer_invoices"),
    "bills": domain_for_move_bucket("vendor_bills"),
    "customer_refunds": domain_for_move_bucket("customer_refunds"),
    "vendor_refunds": domain_for_move_bucket("vendor_refunds"),
    "journal_entries": domain_for_move_bucket("journal_entries"),
}

#: Payment buckets pulled into the single ``payments`` dataset.
PAYMENT_BUCKETS: tuple[str, ...] = (
    "customer_payments_received",
    "refunds_paid_to_customers",
    "vendor_payments_made",
    "refunds_received_from_vendors",
    "internal_transfers",
)

#: Which date column each dataset is filtered on.  Critical: journal entries
#: and GL lines have no ``invoice_date``, so they use ``date``.
DATE_FIELD: dict[str, str] = {
    "invoices": "invoice_date",
    "bills": "invoice_date",
    "customer_refunds": "invoice_date",
    "vendor_refunds": "invoice_date",
    "journal_entries": "date",
    "move_lines": "date",
}

#: Models that must be restricted to a company when --company-id is used.
COMPANY_SCOPED = {
    "account.journal", "account.account", "account.tax", "account.move",
    "account.move.line", "account.payment", "account.analytic.account",
    "account.fiscal.position", "account.payment.term", "product.product",
    "res.users", "res.partner",
}

#: Fields that are relations and therefore need re-mapping on import.
REFERENCE_FIELDS = (
    "company_id", "currency_id", "journal_id", "account_id", "partner_id",
    "tax_ids", "taxes_id", "payment_term_id", "invoice_payment_term_id",
    "move_id", "matched_payment_ids", "matched_payment_move_ids",
    "invoice_line_ids", "line_ids", "reconciled_invoice_ids",
    "reconciled_bill_ids", "default_account_id", "bank_account_id",
    "country_id", "partner_bank_id", "user_id", "fiscal_position_id",
    "full_reconcile_id",
)


def _flatten(value: Any) -> Any:
    """Render a relational value as ``"<name> (<id>)"`` so it stays resolvable."""
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], int):
            return f"{value[1]} ({value[0]})"
        if not value:
            return ""
        return json.dumps(value, default=str)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    return value


def _fetch_rows(
    client: OdooClient,
    model: str,
    fields: Sequence[str],
    domain: list[Any],
    limit: int,
    page: int,
    company_id: int | None,
    dropped: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Stream a model into flat records.

    Unreadable fields (Odoo refuses a whole read when the key lacks rights to
    any one field) are shed and reported in ``dropped`` rather than aborting
    the migration export.
    """
    if company_id and model in COMPANY_SCOPED:
        domain = domain + [("company_id", "=", company_id)]
    rows: list[dict[str, Any]] = []
    for raw in client.iter_search_read_tolerant(model, domain, list(fields), page=page,
                                               order="id asc", dropped=dropped):
        rec: dict[str, Any] = {"old_id": raw.get("id"), "_model": model}
        for key, value in raw.items():
            rec[key] = _flatten(value)
        rows.append(rec)
        if limit and len(rows) >= limit:
            break
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], columns: Sequence[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def build(args: argparse.Namespace, client: OdooClient) -> dict[str, Any]:
    out_dir: Path = Path(args.out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # Live schema drives the column list, so custom fields from real_estate_bits,
    # the dp_* modules, account_loans, account_module_customization and Studio
    # are all carried over. LOAD_ORDER's field tuples are only a fallback.
    try:
        plan = fieldplan.ensure_plan(client, path=args.field_plan,
                                     refresh=args.refresh_fields)
    except Exception as exc:  # noqa: BLE001
        log.warning("Field discovery failed (%s); using static field lists.", exc)
        plan = None

    custom_by_model: dict[str, set[str]] = {}
    if plan:
        custom_by_model = {
            m: fieldplan.custom_field_names(plan, m) for m in (plan.get("models") or {})
        }

    manifest: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_url": client.url,
        "source_database": client.db,
        "source_server": (client.about().get("server_version")),
        "transport": client.transport_name,
        "date_from": args.date_from or "(all)",
        "date_to": args.date_to or "(all)",
        "include_draft": args.include_draft,
        "company_id": args.company_id or "(all)",
        "load_order": [k for k, _, _, _ in LOAD_ORDER],
        "reference_fields": list(REFERENCE_FIELDS),
        "custom_fields_total": (plan or {}).get("total_custom_fields"),
        "non_core_modules": (plan or {}).get("non_core_modules"),
        "datasets": {},
    }

    for key, model, label, fallback_fields in LOAD_ORDER:
        if args.only and key not in args.only:
            continue

        fields = (fieldplan.fields_for(plan, model, fallback_fields)
                  if plan else list(fallback_fields))

        rows: list[dict[str, Any]] = []
        date_field = DATE_FIELD.get(key)
        dropped: list[str] = []

        def scoped(domain: list[Any]) -> list[Any]:
            """Apply the shared draft + date-range filters."""
            domain = list(domain)
            if date_field and model == "account.move" and not args.include_draft:
                domain += [("state", "=", "posted")]
            if date_field:
                if args.date_from:
                    domain += [(date_field, ">=", args.date_from)]
                if args.date_to:
                    domain += [(date_field, "<=", args.date_to)]
            return domain

        if key == "receipts":
            for bucket in ("customer_receipts", "vendor_receipts"):
                rows += _fetch_rows(client, model, fields,
                                    scoped(domain_for_move_bucket(bucket)),
                                    args.limit, args.page, args.company_id, dropped)
        elif key == "payments":
            for bucket in PAYMENT_BUCKETS:
                rows += _fetch_rows(client, model, fields,
                                    scoped(domain_for_payment_bucket(bucket,
                                                                    include_draft=args.include_draft)),
                                    args.limit, args.page, args.company_id, dropped)
        elif key == "move_lines":
            # Full general ledger: every line, not just misc-entry lines.
            rows += _fetch_rows(client, model, fields,
                                domain_for_move_lines(date_from=args.date_from,
                                                      date_to=args.date_to,
                                                      company_id=args.company_id),
                                args.limit, args.page, args.company_id, dropped)
        elif key in FINANCIAL_DOMAINS:
            rows += _fetch_rows(client, model, fields, scoped(FINANCIAL_DOMAINS[key]),
                                args.limit, args.page, args.company_id, dropped)
        else:
            rows += _fetch_rows(client, model, fields, [],
                                args.limit, args.page, args.company_id, dropped)

        custom_cols = sorted(custom_by_model.get(model, set()) & set(fields))

        # Add classification so the importer knows each document's intent.
        if model == "account.move":
            for rec in rows:
                cls = classify_move({"move_type": rec.get("move_type")})
                rec["bucket"] = cls["bucket"]
                rec["is_refund"] = cls["is_refund"]
        elif model == "account.payment":
            for rec in rows:
                cls = classify_payment({"payment_type": rec.get("payment_type"),
                                        "partner_type": rec.get("partner_type")})
                rec["bucket"] = cls["bucket"]
                rec["is_refund"] = cls["is_refund"]

        columns: list[str] = ["old_id", "_model"] + [f for f in fields if f != "id"]
        for extra in ("bucket", "is_refund"):
            if rows and extra in rows[0]:
                columns.append(extra)

        path = out_dir / f"{key}.csv"
        count = write_csv(path, rows, columns)
        manifest["datasets"][key] = {
            "label": label,
            "model": model,
            "file": path.name,
            "rows": count,
            "columns": columns,
            "custom_columns": custom_cols,
            "custom_column_count": len(custom_cols),
            "dropped_unreadable_fields": sorted(set(dropped)),
        }
        if dropped:
            print(f"      ! {len(set(dropped))} field(s) not readable with this key, "
                  f"dropped: {', '.join(sorted(set(dropped))[:10])}"
                  f"{' ...' if len(set(dropped)) > 10 else ''}")
        log.info("%-22s %-20s %8s rows, %3d custom cols -> %s",
                 key, model, f"{count:,}", len(custom_cols), path.name)
        print(f"  {key:24} {model:22} {count:>9,} rows  "
              f"{len(custom_cols):>3} custom cols")

    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(f"\nmanifest.json written to {out_dir}")
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="export_migration.py",
        description="Dependency-ordered, reference-preserving export for database migration.",
    )
    parser.add_argument("--out", default="migration_out", help="Output directory")
    parser.add_argument("--date-from", default=None, help="Inclusive start date, YYYY-MM-DD")
    parser.add_argument("--date-to", default=None, help="Inclusive end date, YYYY-MM-DD")
    parser.add_argument("--company-id", type=int, default=None,
                        help="Restrict every company-scoped model to one company")
    parser.add_argument("--include-draft", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Max rows per dataset, 0=all")
    parser.add_argument("--page", type=int, default=500)
    parser.add_argument("--only", nargs="*", default=None,
                        help="Only export these dataset keys")
    parser.add_argument("--field-plan", default=str(fieldplan.PLAN_PATH),
                        help="Path to the discovered field plan (field_plan.json)")
    parser.add_argument("--refresh-fields", action="store_true",
                        help="Re-probe the live schema instead of reusing the field plan")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(levelname)-7s %(message)s", stream=sys.stderr)

    try:
        client = OdooClient()
    except OdooAuthError as exc:
        print(f"\nAUTHENTICATION FAILED\n\n{exc}\n", file=sys.stderr)
        return 2
    except OdooError as exc:
        print(f"\nCONNECTION FAILED\n\n{exc}\n", file=sys.stderr)
        return 3

    print(f"Source: {client.url} db={client.db} transport={client.transport_name}")
    print(f"Version: {(client.about().get('server_version'))}\n")
    build(args, client)
    print("\nNext: load these CSVs into the target DB in `load_order` order,")
    print("resolving `REFERENCE_FIELDS` by name/code, not by old_id.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())