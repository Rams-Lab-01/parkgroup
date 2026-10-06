"""Bulk-export Parkgroup Real Estate accounting data from Odoo 18.

Downloads every financial document into flat, analysis-ready files:

===========================  ================  ==================================
dataset                      Odoo model        Odoo semantics
===========================  ================  ==================================
``customer_invoices``        account.move      ``move_type = out_invoice``
``customer_refunds``         account.move      ``move_type = out_refund``
``vendor_bills``             account.move      ``move_type = in_invoice``
``vendor_refunds``           account.move      ``move_type = in_refund``
``customer_receipts``        account.move      ``move_type = out_receipt``
``vendor_receipts``          account.move      ``move_type = in_receipt``
``journal_entries``          account.move      ``move_type = entry``
``journal_entry_lines``      account.move.line line detail for the above
``customer_payments_received``   account.payment  inbound  + customer
``refunds_paid_to_customers``    account.payment  outbound + customer
``vendor_payments_made``         account.payment  outbound + supplier
``refunds_received_from_vendors`` account.payment inbound + supplier
``internal_transfers``           account.payment  internal
``partners``                 res.partner      customers and vendors
``journals``                 account.journal   all journals
===========================  ================  ==================================

Amounts are reported **per currency** and never summed across currencies -
the ledger is AED with USD property sales, so a single blended total would be
meaningless.

Usage
-----
    python export_data.py --format xlsx
    python export_data.py --format both --date-from 2025-01-01 --date-to 2025-12-31
    python export_data.py --format csv --limit 500

Credentials come from the environment (``PGRE_URL``, ``PGRE_DB``, ``PGRE_LOGIN``,
``PGRE_KEY``); see ``.env.example`` / the README.  Nothing is hardcoded.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import accounting as _accounting
import fieldplan
from accounting import (
    ACCOUNT_FIELDS,
    INVOICE_FIELDS,
    JOURNAL_FIELDS,
    MOVE_LINE_FIELDS,
    MOVE_TYPE_BUCKETS,
    PARTNER_FIELDS,
    PAYMENT_FIELDS,
    PAYMENT_TYPE_BUCKETS,
    classify_move,
    classify_payment,
    domain_for_journal_entries,
    domain_for_journal_entry_lines,
    domain_for_move_bucket,
    domain_for_payment_bucket,
    human_bucket,
    human_payment_bucket,
)
from pgre_client import OdooAuthError, OdooClient, OdooError

log = logging.getLogger("pgre.export")

#: Labels for the export sheets, derived from accounting.py so there is one
#: source of truth for bucket naming.
MOVE_DATASETS: dict[str, tuple[str, str]] = {
    bucket: (f"{human_bucket(types[0])}", "account.move")
    for bucket, types in MOVE_TYPE_BUCKETS.items()
}
PAYMENT_DATASETS: dict[str, tuple[str, str]] = {
    bucket: (human_payment_bucket(*spec), "account.payment")
    for bucket, spec in PAYMENT_TYPE_BUCKETS.items()
}

#: Columns that should be formatted as money in the workbook.
AMOUNT_HINTS = ("amount", "debit", "credit", "balance", "price", "total", "residual")

#: Export order for the workbook / summary.
DATASET_ORDER: list[str] = [
    "customer_invoices", "customer_refunds", "customer_receipts",
    "vendor_bills", "vendor_refunds", "vendor_receipts",
    "customer_payments_received", "refunds_paid_to_customers",
    "vendor_payments_made", "refunds_received_from_vendors", "internal_transfers",
    "journal_entries", "journal_entry_lines",
    "partners", "journals", "accounts",
]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _flatten(value: Any, key: str) -> Any:
    """Turn an Odoo relational tuple into a readable scalar.

    ``[8, "ACME Ltd"]`` -> ``"ACME Ltd (8)"`` so the id is not lost in a CSV.
    """
    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], int):
            return f"{value[1]} ({value[0]})"
        return json.dumps(value, default=str)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    return value


def _row_to_record(
    raw: dict[str, Any],
    dataset: str,
    model: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten one Odoo row into a flat CSV/XLSX record."""
    rec: dict[str, Any] = {"dataset": dataset, "model": model}
    for key, value in raw.items():
        rec[key] = _flatten(value, key)
    if model == "account.move":
        cls = classify_move(raw)
        rec["classification_bucket"] = cls["bucket"]
        rec["classification_label"] = cls["label"]
        rec["is_refund"] = cls["is_refund"]
        rec["direction"] = cls["direction"]
        rec["counterparty_type"] = cls["counterparty_type"]
        # Move `date` across so every dataset has a single comparable date column.
        rec.setdefault("date", raw.get("invoice_date") or raw.get("date"))
    elif model == "account.payment":
        cls = classify_payment(raw)
        rec["classification_bucket"] = cls["bucket"]
        rec["classification_label"] = cls["label"]
        rec["is_refund"] = cls["is_refund"]
        rec["direction"] = cls["direction"]
        rec["counterparty_type"] = cls["counterparty_type"]
        rec["date"] = raw.get("date")
    if extra:
        rec.update(extra)
    return rec


def _collect(
    client: OdooClient,
    model: str,
    domain: list[Any],
    fields: Sequence[str],
    dataset: str,
    limit: int,
    page: int,
    enrich: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    dropped: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Stream a model into a list of flat records, with progress logging.

    Unreadable fields are shed and reported in ``dropped`` instead of aborting.
    """
    records: list[dict[str, Any]] = []
    for raw in client.iter_search_read_tolerant(model, domain, list(fields), page=page,
                                               order="id asc", dropped=dropped):
        records.append(_row_to_record(raw, dataset, model, enrich(raw) if enrich else None))
        if limit and len(records) >= limit:
            break
        if len(records) % 500 == 0:
            log.info("  %s: %d records...", dataset, len(records))
    return records


def _union_columns(tables: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Stable union of every row's keys, preserving first-seen order."""
    cols: list[str] = []
    seen: set[str] = set()
    for rows in tables.values():
        for row in rows:
            for key in row:
                if key not in seen:
                    seen.add(key)
                    cols.append(key)
    return cols


def _totals_by_currency(tables: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, dict[str, float]]]:
    """dataset -> currency label -> summed amount fields.

    Sums happen strictly *within* one currency key, so no total ever mixes
    currencies.  The currency label is taken from the flattened
    ``currency_id`` value Odoo returns for each row.
    """
    money_fields = ("amount_total", "amount", "debit", "credit")
    out: dict[str, dict[str, dict[str, float]]] = {}
    for dataset, rows in tables.items():
        per_ccy: dict[str, dict[str, float]] = {}
        for row in rows:
            ccy_raw = row.get("currency_id")
            ccy = str(ccy_raw) if ccy_raw else "?"
            agg = per_ccy.setdefault(ccy, {"count": 0.0, **{f: 0.0 for f in money_fields}})
            agg["count"] += 1
            for field in money_fields:
                raw_val = row.get(field)
                try:
                    agg[field] += float(raw_val) if raw_val not in (None, "") else 0.0
                except (TypeError, ValueError):
                    continue
        out[dataset] = per_ccy
    return out


# --------------------------------------------------------------------------- #
# Writers
# --------------------------------------------------------------------------- #
def write_csvs(out_dir: Path, tables: dict[str, list[dict[str, Any]]]) -> list[Path]:
    """One UTF-8-BOM CSV per dataset (BOM keeps Excel happy with Unicode)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for dataset, rows in tables.items():
        path = out_dir / f"{dataset}.csv"
        cols = _union_columns({dataset: rows}) or ["dataset"]
        with path.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        written.append(path)
    return written


def write_xlsx(out_dir: Path, tables: dict[str, list[dict[str, Any]]], meta: dict[str, Any]) -> Path:
    """One workbook, one sheet per dataset, plus a `_meta` sheet."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "odoo_financial_export.xlsx"

    wb = Workbook()
    wb.remove(wb.active)

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="1F4E78")

    # ---- _meta sheet
    ws_meta = wb.create_sheet("_meta")
    ws_meta.append(["key", "value"])
    for cell in ws_meta[1]:
        cell.font = header_font
        cell.fill = header_fill
    for key, value in meta.items():
        ws_meta.append([key, value if not isinstance(value, (dict, list)) else str(value)])
    ws_meta.column_dimensions["A"].width = 26
    ws_meta.column_dimensions["B"].width = 90

    # ---- one sheet per dataset
    for dataset in DATASET_ORDER:
        rows = tables.get(dataset)
        if rows is None:
            continue
        cols = _union_columns({dataset: rows}) or ["dataset"]
        ws = wb.create_sheet(dataset[:31])
        ws.append(cols)
        for cell in ws[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        money_cols = {c for c in cols if any(h in c for h in AMOUNT_HINTS)}

        for row in rows:
            ws.append([row.get(c) for c in cols])

        # Formats + widths
        for idx, col in enumerate(cols, start=1):
            letter = get_column_letter(idx)
            if col in money_cols:
                for cell in ws[letter][1:]:
                    if isinstance(cell.value, (int, float)):
                        cell.number_format = "#,##0.00"
            else:
                longest = max((len(str(r.get(col) or "")) for r in rows[:500]), default=10)
                ws.column_dimensions[letter].width = min(max(longest + 2, 10), 50)
        ws.freeze_panes = "A2"
        if rows:
            ws.auto_filter.ref = ws.dimensions

    wb.save(path)
    return path


# --------------------------------------------------------------------------- #
# Main export
# --------------------------------------------------------------------------- #
def build_tables(args: argparse.Namespace, client: OdooClient) -> dict[str, list[dict[str, Any]]]:
    """Fetch every dataset. Returns dataset -> flat records.

    Field lists come from the **live schema** (``fieldplan``) rather than a
    hardcoded tuple, so custom fields added by real_estate_bits, the dp_*
    modules, account_loans, Studio etc. are all exported. Falls back to the
    static lists in ``accounting`` if discovery is unavailable.
    """
    tables: dict[str, list[dict[str, Any]]] = {}
    include_draft = bool(args.include_draft)

    try:
        plan = fieldplan.ensure_plan(client, path=args.field_plan, refresh=args.refresh_fields)
        move_fields = fieldplan.fields_for(plan, "account.move", INVOICE_FIELDS)
        payment_fields = fieldplan.fields_for(plan, "account.payment", PAYMENT_FIELDS)
        line_fields = fieldplan.fields_for(plan, "account.move.line", MOVE_LINE_FIELDS)
        journal_fields = fieldplan.fields_for(plan, "account.journal", JOURNAL_FIELDS)
        partner_fields = fieldplan.fields_for(plan, "res.partner", PARTNER_FIELDS)
        account_fields = fieldplan.fields_for(plan, "account.account", ACCOUNT_FIELDS)
        custom_note = (f"{plan.get('total_custom_fields', 0)} custom fields included "
                       f"across {len(plan.get('models') or {})} models")
        log.info("Field plan: %d custom fields; %s",
                 plan.get("total_custom_fields", 0), custom_note)
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort
        log.warning("Field discovery failed (%s); using static field lists.", exc)
        move_fields, payment_fields = list(INVOICE_FIELDS), list(PAYMENT_FIELDS)
        line_fields, journal_fields = list(MOVE_LINE_FIELDS), list(JOURNAL_FIELDS)
        partner_fields, account_fields = list(PARTNER_FIELDS), list(ACCOUNT_FIELDS)

    # ---- account.move datasets
    for bucket in MOVE_TYPE_BUCKETS:
        domain = domain_for_move_bucket(
            bucket,
            date_from=args.date_from,
            date_to=args.date_to,
            company_id=args.company_id,
            include_draft=include_draft,
        )
        log.info("Fetching %s ...", bucket)
        tables[bucket] = _collect(client, "account.move", domain, move_fields, bucket,
                                  args.limit, args.page)

    # ---- account.payment datasets
    for bucket in PAYMENT_TYPE_BUCKETS:
        domain = domain_for_payment_bucket(
            bucket,
            date_from=args.date_from,
            date_to=args.date_to,
            company_id=args.company_id,
            include_draft=include_draft,
        )
        log.info("Fetching %s ...", bucket)
        tables[bucket] = _collect(client, "account.payment", domain, payment_fields, bucket,
                                  args.limit, args.page)

    # ---- journal entry lines (GL detail for the misc entries).
    # NB: account.move.line has no `state` column; the builder uses
    # parent_state, so this cannot reuse the account.move domain.
    je_domain = domain_for_journal_entry_lines(
        date_from=args.date_from,
        date_to=args.date_to,
        company_id=args.company_id,
        include_draft=include_draft,
    )
    log.info("Fetching journal_entry_lines ...")
    tables["journal_entry_lines"] = _collect(
        client, "account.move.line", je_domain, line_fields,
        "journal_entry_lines", args.limit, args.page,
    )

    # ---- reference data
    log.info("Fetching partners ...")
    tables["partners"] = _collect(
        client, "res.partner", [("active", "=", True)], partner_fields,
        "partners", args.limit, args.page,
    )
    log.info("Fetching journals ...")
    tables["journals"] = _collect(
        client, "account.journal", [], journal_fields,
        "journals", args.limit, args.page,
    )
    log.info("Fetching accounts ...")
    tables["accounts"] = _collect(
        client, "account.account", [], account_fields,
        "accounts", args.limit, args.page,
    )
    return tables


def print_summary(tables: dict[str, list[dict[str, Any]]], totals: dict[str, Any]) -> None:
    print("\n" + "=" * 78)
    print("EXPORT SUMMARY".center(78))
    print("=" * 78)
    print(f"{'dataset':34} {'rows':>7}  totals (per currency - do not mix)")
    print("-" * 78)
    for dataset in DATASET_ORDER:
        rows = tables.get(dataset)
        if not rows:
            continue
        per_ccy = totals.get(dataset, {})
        parts: list[str] = []
        for ccy, agg in list(per_ccy.items())[:4]:
            money = ""
            for field in ("amount_total", "amount", "debit"):
                if agg.get(field):
                    money = f"{field}={agg[field]:,.2f}"
                    break
            parts.append(f"{ccy.split('(')[0].strip()}: {money}")
        print(f"{dataset:34} {len(rows):>7}  {' | '.join(parts) if parts else '-'}")
    print("-" * 78)
    print("Note: totals are computed per currency. Never add figures across")
    print("      different currency rows (AED books, USD property sales).")
    print("=" * 78)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="export_data.py",
        description="Export all Odoo invoices, bills, refunds, payments and journal entries.",
    )
    parser.add_argument("--out", default="data", help="Output directory (default: ./data)")
    parser.add_argument("--format", choices=["csv", "xlsx", "both"], default="xlsx")
    parser.add_argument("--date-from", default=None, help="Inclusive start date, YYYY-MM-DD")
    parser.add_argument("--date-to", default=None, help="Inclusive end date, YYYY-MM-DD")
    parser.add_argument("--include-draft", action="store_true",
                        help="Include draft documents (default: posted only)")
    parser.add_argument("--company-id", type=int, default=None, help="Restrict to one company")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max rows per dataset, 0 = unlimited (default)")
    parser.add_argument("--page", type=int, default=500,
                        help="Rows per RPC call (default: 500)")
    parser.add_argument("--field-plan", default=str(fieldplan.PLAN_PATH),
                        help="Path to the discovered field plan (field_plan.json)")
    parser.add_argument("--refresh-fields", action="store_true",
                        help="Re-probe the live schema instead of reusing the field plan")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stderr,
    )
    out_dir = Path(args.out).expanduser().resolve()

    try:
        client = OdooClient()
    except OdooAuthError as exc:
        print(f"\nAUTHENTICATION FAILED\n\n{exc}\n", file=sys.stderr)
        return 2
    except OdooError as exc:
        print(f"\nCONNECTION FAILED\n\n{exc}\n", file=sys.stderr)
        return 3

    about = client.about()
    log.info("Connected: %s (db=%s, uid=%s, transport=%s)",
             about.get("server_version"), about.get("db"),
             about.get("uid"), about.get("transport"))

    tables = build_tables(args, client)
    totals = _totals_by_currency(tables)

    # Custom-field provenance, so the workbook records what was captured and
    # which columns came from non-core modules.
    custom: dict[str, Any] = {}
    try:
        plan = fieldplan.load_plan(args.field_plan)
        if plan:
            custom = {
                "total_custom_fields": plan.get("total_custom_fields"),
                "non_core_modules": plan.get("non_core_modules"),
                "per_model_custom": {
                    m: e.get("custom_count")
                    for m, e in (plan.get("models") or {}).items()
                },
            }
    except Exception as exc:  # noqa: BLE001
        log.debug("field plan unavailable for meta: %s", exc)

    meta: dict[str, Any] = {
        "source_url": about.get("url"),
        "database": about.get("db"),
        "server_version": about.get("server_version"),
        "transport": about.get("transport"),
        "authenticated_user": (about.get("user") or {}).get("login"),
        "company": (about.get("company") or {}).get("name"),
        "exported_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date_from": args.date_from or "(all)",
        "date_to": args.date_to or "(all)",
        "include_draft": args.include_draft,
        "company_id": args.company_id or "(all)",
        "row_counts": {k: len(v) for k, v in tables.items()},
        "currency_note": "Amounts are per currency; totals across different "
                         "currencies are not meaningful and are never combined.",
        "custom_fields": custom,
    }

    written: list[Path] = []
    if args.format in ("csv", "both"):
        written += write_csvs(out_dir, tables)
        log.info("Wrote %d CSV files", len(written))
    if args.format in ("xlsx", "both"):
        path = write_xlsx(out_dir, tables, meta)
        written.append(path)
        log.info("Wrote %s", path)

    print_summary(tables, totals)
    print("\nFiles written:")
    for path in written:
        print(f"  {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())