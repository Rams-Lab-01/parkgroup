"""Validate every declared field against the live Odoo schema.

Field names drift between Odoo versions - ``amount_credit``/``amount_debit`` do
not exist on ``account.move`` in v18, ``amount_currency``/``payment_date`` do not
exist on ``account.payment``, and ``account.account`` uses ``company_ids``
(many2many) rather than ``company_id``.  This script catches that class of bug
before a long export starts, and covers the ad-hoc field lists in
``server.py`` and ``export_migration.py`` as well.

    python validate_fields.py

Exit codes: 0 all valid, 1 at least one unknown field.
"""

from __future__ import annotations

import sys

import accounting as A
from pgre_client import OdooClient, OdooError

#: Field lists declared in accounting.py
DECLARED: dict[str, tuple[str, tuple[str, ...]]] = {
    "accounting.INVOICE_FIELDS": ("account.move", A.INVOICE_FIELDS),
    "accounting.PAYMENT_FIELDS": ("account.payment", A.PAYMENT_FIELDS),
    "accounting.MOVE_LINE_FIELDS": ("account.move.line", A.MOVE_LINE_FIELDS),
    "accounting.JOURNAL_FIELDS": ("account.journal", A.JOURNAL_FIELDS),
    "accounting.PARTNER_FIELDS": ("res.partner", A.PARTNER_FIELDS),
    "accounting.ACCOUNT_FIELDS": ("account.account", A.ACCOUNT_FIELDS),
}

#: Ad-hoc field lists embedded in server.py / export_migration.py.
EXTRA: dict[str, tuple[str, tuple[str, ...]]] = {
    "server.financial_summary.move": ("account.move",
                                      ("amount_total", "amount_residual", "amount_paid",
                                       "currency_id", "state")),
    "server.financial_summary.payment": ("account.payment",
                                         ("amount", "amount_company_currency_signed",
                                          "currency_id")),
    "migration.companies": ("res.company",
                            ("id", "name", "partner_id", "currency_id", "parent_id",
                             "country_id", "vat", "street", "city", "zip",
                             "email", "phone")),
    "migration.currencies": ("res.currency",
                             ("id", "name", "symbol", "rounding", "decimal_places",
                              "active", "position")),
    "migration.countries": ("res.country", ("id", "name", "code")),
    "migration.journals": ("account.journal",
                           ("id", "code", "name", "type", "company_id", "currency_id",
                            "bank_account_id", "default_account_id", "active")),
    "migration.accounts": ("account.account",
                           ("id", "code", "code_store", "name", "account_type",
                            "internal_group", "reconcile", "currency_id")),
    "migration.taxes": ("account.tax",
                        ("id", "name", "amount", "amount_type", "tax_group_id",
                         "company_id", "price_include_override", "active")),
    "migration.payment_terms": ("account.payment.term",
                                ("id", "name", "note", "company_id", "active")),
    "migration.partners": ("res.partner",
                           ("id", "name", "ref", "email", "phone", "mobile", "vat",
                            "country_id", "company_id", "parent_id", "customer_rank",
                            "supplier_rank", "is_company", "active", "type")),
    "migration.products": ("product.product",
                           ("id", "name", "default_code", "type", "list_price",
                            "standard_price", "taxes_id", "company_id", "active")),
    "migration.users": ("res.users",
                        ("id", "name", "login", "email", "company_id",
                         "partner_id", "active")),
    "migration.analytic_accounts": ("account.analytic.account",
                                    ("id", "name", "code", "company_id", "partner_id",
                                     "plan_id", "active")),
    "migration.fiscal_positions": ("account.fiscal.position",
                                   ("id", "name", "company_id", "auto_apply", "country_id")),
}

#: Fields the *runtime* logic depends on existing. A missing one is a real bug,
#: not just noise.
CRITICAL: dict[tuple[str, str], str] = {
    ("account.move", "move_type"): "bucket classification depends on this",
    ("account.move", "state"): "posted/draft filtering depends on this",
    ("account.move", "amount_total"): "invoice totals depend on this",
    ("account.move", "amount_residual"): "unpaid/aging depends on this",
    ("account.move", "currency_id"): "per-currency totals depend on this",
    ("account.move", "invoice_date"): "invoice date filtering depends on this",
    ("account.move", "date"): "journal-entry date filtering depends on this",
    ("account.payment", "payment_type"): "payment buckets depend on this",
    ("account.payment", "partner_type"): "payment buckets depend on this",
    ("account.payment", "amount"): "payment totals depend on this",
    ("account.payment", "date"): "payment date filtering depends on this",
    ("account.move.line", "debit"): "GL debit totals depend on this",
    ("account.move.line", "credit"): "GL credit totals depend on this",
    ("account.move.line", "move_id"): "GL drill-down depends on this",
    ("account.account", "code"): "chart-of-accounts import mapping depends on this",
    ("res.partner", "name"): "partner import mapping depends on this",
}


def main() -> int:
    try:
        client = OdooClient()
    except OdooError as exc:
        print(f"Cannot validate without a connection: {exc}", file=sys.stderr)
        return 1

    print(f"Connected: {client.url} db={client.db} "
          f"({client.about().get('server_version')})\n")

    schema_cache: dict[str, set[str]] = {}

    def real_fields(model: str) -> set[str]:
        if model not in schema_cache:
            schema_cache[model] = set(client.fields_get(model, attributes=["type"]))
        return schema_cache[model]

    problems: list[str] = []
    print("=" * 78)
    print("DECLARED FIELD LISTS")
    print("=" * 78)
    for label, (model, fields) in {**DECLARED, **EXTRA}.items():
        real = real_fields(model)
        bad = [f for f in fields if f not in real]
        status = "OK" if not bad else f"INVALID -> {bad}"
        print(f"  {label:<32} {model:<22} {len(fields):>3} fields  {status}")
        for f in bad:
            problems.append(f"{label}: '{f}' does not exist on {model}")

    print()
    print("=" * 78)
    print("CRITICAL FIELDS THE RUNTIME LOGIC DEPENDS ON")
    print("=" * 78)
    for (model, field), why in CRITICAL.items():
        ok = field in real_fields(model)
        print(f"  {'OK  ' if ok else 'MISS'} {model}.{field:<28} {why}")
        if not ok:
            problems.append(f"CRITICAL {model}.{field} missing - {why}")

    print()
    print("=" * 78)
    if problems:
        print(f"RESULT: FAIL - {len(problems)} problem(s)")
        for p in problems:
            print(f"  - {p}")
        print("=" * 78)
        return 1
    print("RESULT: PASS - every declared field exists in the live schema")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())