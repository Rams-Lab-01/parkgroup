"""Offline self-test for the Odoo MCP modules.

Runs with **no network access** and **no Odoo credentials**: it only exercises
the pure domain/classification logic and asserts that importing the MCP server
module does not try to authenticate.

    python selftest.py        # exits 0 when everything passes
"""

from __future__ import annotations

import sys

import accounting as A

_FAILURES: list[str] = []
_CHECKS = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global _CHECKS
    _CHECKS += 1
    if condition:
        print(f"  PASS  {label}")
    else:
        print(f"  FAIL  {label}{(' -> ' + detail) if detail else ''}")
        _FAILURES.append(label)


def _fields_in(domain: list, field: str) -> bool:
    """True if any clause in ``domain`` constrains ``field``."""
    return any(isinstance(c, (list, tuple)) and c and c[0] == field for c in domain)


def _has(domain: list, field: str, op: str, value: object = None) -> bool:
    """True if ``domain`` contains the clause ``field op value``.

    Odoo accepts both ``('a','=',1)`` and ``['a','=',1]`` as identical clauses,
    so this compares the normalised triple rather than the container type.
    """
    for clause in domain:
        if isinstance(clause, (list, tuple)) and len(clause) >= 2 and clause[0] == field and clause[1] == op:
            if value is None or (len(clause) > 2 and clause[2] == value):
                return True
    return False


def test_bucket_definitions() -> None:
    print("\n[1] bucket definitions")
    check("7 move buckets defined", len(A.MOVE_TYPE_BUCKETS) == 7,
          f"got {len(A.MOVE_TYPE_BUCKETS)}")
    check("5 payment buckets defined", len(A.PAYMENT_TYPE_BUCKETS) == 5,
          f"got {len(A.PAYMENT_TYPE_BUCKETS)}")
    check("customer_invoices -> out_invoice",
          A.MOVE_TYPE_BUCKETS["customer_invoices"] == ["out_invoice"])
    check("vendor_bills -> in_invoice",
          A.MOVE_TYPE_BUCKETS["vendor_bills"] == ["in_invoice"])
    check("customer_refunds -> out_refund",
          A.MOVE_TYPE_BUCKETS["customer_refunds"] == ["out_refund"])
    check("vendor_refunds -> in_refund",
          A.MOVE_TYPE_BUCKETS["vendor_refunds"] == ["in_refund"])
    check("journal_entries -> entry",
          A.MOVE_TYPE_BUCKETS["journal_entries"] == ["entry"])


def test_move_classification() -> None:
    print("\n[2] account.move classification")
    ci = A.classify_move({"move_type": "out_invoice"})
    check("out_invoice -> customer_invoices", ci["bucket"] == "customer_invoices")
    check("out_invoice counterparty=customer", ci["counterparty_type"] == "customer")
    check("out_invoice is not a refund", ci["is_refund"] is False)

    cr = A.classify_move({"move_type": "out_refund"})
    check("out_refund -> customer_refunds", cr["bucket"] == "customer_refunds")
    check("out_refund is_refund is True", cr["is_refund"] is True)

    vb = A.classify_move({"move_type": "in_invoice"})
    check("in_invoice -> vendor_bills", vb["bucket"] == "vendor_bills")
    check("in_invoice counterparty=supplier", vb["counterparty_type"] == "supplier")

    vr = A.classify_move({"move_type": "in_refund"})
    check("in_refund -> vendor_refunds", vr["bucket"] == "vendor_refunds")
    check("in_refund is_refund is True", vr["is_refund"] is True)

    je = A.classify_move({"move_type": "entry"})
    check("entry -> journal_entries", je["bucket"] == "journal_entries")
    check("entry counterparty=none", je["counterparty_type"] == "none")

    check("missing move_type does not raise",
          A.classify_move({"id": 1})["bucket"] is None)
    check("None move_type does not raise",
          A.classify_move({"move_type": None})["bucket"] is None)
    check("garbage move_type does not raise",
          A.classify_move({"move_type": "bogus"})["bucket"] is None)
    check("empty row does not raise", A.classify_move({})["direction"] == "none")


def test_payment_classification() -> None:
    print("\n[3] account.payment classification")
    cpr = A.classify_payment({"payment_type": "inbound", "partner_type": "customer"})
    check("inbound+customer -> customer_payments_received",
          cpr["bucket"] == "customer_payments_received")
    check("inbound+customer direction=inbound", cpr["direction"] == "inbound")

    rpc = A.classify_payment({"payment_type": "outbound", "partner_type": "customer"})
    check("outbound+customer -> refunds_paid_to_customers",
          rpc["bucket"] == "refunds_paid_to_customers")
    check("outbound+customer is_refund is True", rpc["is_refund"] is True)

    vpm = A.classify_payment({"payment_type": "outbound", "partner_type": "supplier"})
    check("outbound+supplier -> vendor_payments_made",
          vpm["bucket"] == "vendor_payments_made")
    check("outbound+supplier is_refund is False", vpm["is_refund"] is False)

    rfv = A.classify_payment({"payment_type": "inbound", "partner_type": "supplier"})
    check("inbound+supplier -> refunds_received_from_vendors",
          rfv["bucket"] == "refunds_received_from_vendors")
    check("inbound+supplier is_refund is True", rfv["is_refund"] is True)

    it = A.classify_payment({"payment_type": "internal", "partner_type": "customer"})
    check("internal -> internal_transfers", it["bucket"] == "internal_transfers")
    check("internal direction=none", it["direction"] == "none")
    check("internal ignores partner_type",
          A.classify_payment({"payment_type": "internal",
                              "partner_type": "supplier"})["bucket"] == "internal_transfers")
    check("internal with no partner_type still classifies",
          A.classify_payment({"payment_type": "internal"})["bucket"] == "internal_transfers")

    check("missing payment_type does not raise",
          A.classify_payment({})["bucket"] is None)


def test_move_domains() -> None:
    print("\n[4] account.move domain builders")
    d = A.domain_for_move_bucket("journal_entries", date_from="2025-01-01")
    check("journal_entries filters on `date`", _fields_in(d, "date"))
    check("journal_entries never filters on `invoice_date`", not _fields_in(d, "invoice_date"))

    d = A.domain_for_move_bucket("customer_invoices", date_from="2025-01-01")
    check("customer_invoices filters on `invoice_date`", _fields_in(d, "invoice_date"))
    check("customer_invoices does not filter on `date`", not _fields_in(d, "date"))

    d = A.domain_for_move_bucket("customer_invoices", include_draft=False)
    check("include_draft=False adds state=posted", _has(d, "state", "=", "posted"))

    d = A.domain_for_move_bucket("customer_invoices", include_cancel=False)
    check("include_cancel=False excludes cancel", _has(d, "state", "not in", ["cancel"]))

    d = A.domain_for_move_bucket("vendor_bills", partner_id=42, journal_id=7, company_id=3)
    check("partner_id filter applied", _has(d, "partner_id", "=", 42))
    check("journal_id filter applied", _has(d, "journal_id", "=", 7))
    check("company_id filter applied", _has(d, "company_id", "=", 3))

    d = A.domain_for_move_bucket("customer_invoices", payment_state="not_paid")
    check("payment_state filter applied", _has(d, "payment_state", "=", "not_paid"))

    d = A.domain_for_move_bucket("customer_invoices", date_from="2025-01-01",
                                 date_to="2025-03-31")
    check("date_from is inclusive >=", _has(d, "invoice_date", ">=", "2025-01-01"))
    check("date_to is inclusive <=", _has(d, "invoice_date", "<=", "2025-03-31"))

    d = A.domain_for_move_bucket("customer_refunds")
    check("move_type filter uses the bucket's types",
          ("move_type", "in", ["out_refund"]) in d)

    check("date_field_for_bucket(entry) == 'date'",
          A.date_field_for_bucket("journal_entries") == "date")
    check("date_field_for_bucket(invoice) == 'invoice_date'",
          A.date_field_for_bucket("vendor_bills") == "invoice_date")

    raised = False
    try:
        A.domain_for_move_bucket("bogus_bucket")
    except ValueError:
        raised = True
    check("unknown bucket raises ValueError", raised)


def test_payment_domains() -> None:
    print("\n[5] account.payment domain builders")
    d = A.domain_for_payment_bucket("internal_transfers")
    check("internal_transfers does NOT constrain partner_type",
          not _fields_in(d, "partner_type"))
    check("internal_transfers constrains payment_type",
          _has(d, "payment_type", "=", "internal"))

    d = A.domain_for_payment_bucket("customer_payments_received")
    check("customer payments constrain partner_type",
          _has(d, "partner_type", "=", "customer"))
    check("customer payments constrain payment_type",
          _has(d, "payment_type", "=", "inbound"))

    d = A.domain_for_payment_bucket("vendor_payments_made", date_from="2025-06-01")
    check("payments filter on `date`", _has(d, "date", ">=", "2025-06-01"))

    d = A.domain_for_payment_bucket("customer_payments_received", include_draft=False)
    check("include_draft=False excludes draft+cancel",
          _has(d, "state", "not in", ["draft", "cancel"]))

    raised = False
    try:
        A.domain_for_payment_bucket("bogus_bucket")
    except ValueError:
        raised = True
    check("unknown payment bucket raises ValueError", raised)


def test_line_domains() -> None:
    print("\n[4b] account.move.line domains")
    # Regression: an account.move domain reused on account.move.line fails with
    # "Invalid field account.move.line.state" - lines expose parent_state.
    d = A.domain_for_journal_entry_lines(include_draft=False)
    check("journal entry lines scope to move_type=entry",
          ("move_type", "=", "entry") in d)
    check("lines never filter on `state`", not _fields_in(d, "state"))
    check("lines filter on `parent_state` when excluding drafts",
          _has(d, "parent_state", "=", "posted"))
    d = A.domain_for_journal_entry_lines(include_cancel=False)
    check("lines exclude cancelled parents",
          _has(d, "parent_state", "not in", ["cancel"]))
    d = A.domain_for_journal_entry_lines(date_from="2025-01-01", date_to="2025-12-31")
    check("lines filter on `date`", _has(d, "date", ">=", "2025-01-01")
          and _has(d, "date", "<=", "2025-12-31"))
    d = A.domain_for_journal_entry_lines(include_draft=True)
    # include_draft=True only means "don't restrict to posted"; cancelled
    # parents are still excluded by include_cancel=False.
    check("lines include drafts by default",
          not _has(d, "parent_state", "=", "posted"))

    d = A.domain_for_move_lines(move_type="entry")
    check("generic line domain can filter move_type",
          _has(d, "move_type", "=", "entry"))
    d = A.domain_for_move_lines()
    check("generic line domain is empty when unfiltered", d == [])
    d = A.domain_for_move_lines(account_id=42, partner_id=7)
    check("generic line domain filters account/partner",
          _has(d, "account_id", "=", 42) and _has(d, "partner_id", "=", 7))


def test_labels() -> None:
    print("\n[6] human labels")
    check("out_refund label mentions refund",
          "refund" in A.human_bucket("out_refund").lower())
    check("in_invoice label is Vendor Bill", A.human_bucket("in_invoice") == "Vendor Bill")
    check("None label is Unknown", A.human_bucket(None) == "Unknown")
    check("payment label resolves",
          A.human_payment_bucket("inbound", "customer") == "Customer Payment Received")


def test_no_auth_on_import() -> None:
    print("\n[7] import-time safety")
    import os

    # Poison the credentials so any accidental authentication blows up loudly.
    os.environ["PGRE_URL"] = "http://127.0.0.1:1"
    os.environ["PGRE_DB"] = "nonexistent"
    os.environ["PGRE_KEY"] = "not-a-real-key"
    os.environ["PGRE_LOGIN"] = "nobody@example.invalid"

    try:
        import server  # noqa: F401
    except Exception as exc:  # pragma: no cover - would be a real regression
        check("importing server does not authenticate", False, f"{type(exc).__name__}: {exc}")
        return
    check("importing server does not authenticate", True)

    has_tool = hasattr(server.mcp, "tool") or hasattr(server, "mcp")
    check("server exposes a FastMCP instance", has_tool)

    tools = [n for n in dir(server) if not n.startswith("_")]
    for expected in ("odoo_whoami", "list_financial_buckets", "get_invoices",
                     "get_payments", "get_journal_entries", "get_move_lines",
                     "list_journals", "list_partners", "financial_summary",
                     "find_unpaid"):
        check(f"tool `{expected}` is defined", expected in tools)


def test_field_lists() -> None:
    print("\n[8] field lists")
    for name, fields, required in (
        ("INVOICE_FIELDS", A.INVOICE_FIELDS,
         ("id", "name", "move_type", "partner_id", "amount_total",
          "amount_residual", "currency_id", "invoice_date", "payment_state")),
        ("PAYMENT_FIELDS", A.PAYMENT_FIELDS,
         ("id", "name", "payment_type", "partner_type", "amount",
          "currency_id", "date", "is_reconciled")),
        ("MOVE_LINE_FIELDS", A.MOVE_LINE_FIELDS,
         ("id", "move_id", "account_id", "debit", "credit", "date")),
        ("JOURNAL_FIELDS", A.JOURNAL_FIELDS, ("id", "code", "name", "type")),
    ):
        missing = [f for f in required if f not in fields]
        check(f"{name} contains all required fields", not missing, f"missing {missing}")


def main() -> int:
    print("=" * 70)
    print("pgre odoo_mcp - offline self-test (no network, no credentials)")
    print("=" * 70)
    for fn in (
        test_bucket_definitions,
        test_move_classification,
        test_payment_classification,
        test_move_domains,
        test_payment_domains,
        test_line_domains,
        test_labels,
        test_field_lists,
        test_no_auth_on_import,
    ):
        fn()
    print("\n" + "=" * 70)
    if _FAILURES:
        print(f"RESULT: FAIL - {len(_FAILURES)}/{_CHECKS} checks failed")
        for name in _FAILURES:
            print(f"  - {name}")
        print("=" * 70)
        return 1
    print(f"RESULT: PASS - all {_CHECKS} checks passed")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())