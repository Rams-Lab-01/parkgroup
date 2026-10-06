"""Accounting domain logic for the Parkgroup Real Estate Odoo MCP server.

This module is deliberately **offline**: it only contains constants, Odoo
domain builders and pure classification helpers.  Importing it performs no
network access, which keeps it unit-testable (see ``selftest.py``).

Odoo 18 ``account.move.move_type`` semantics
--------------------------------------------
======================  =========================================================
``out_invoice``         Customer Invoice
``out_refund``          Customer Credit Note (a refund we owe the customer)
``in_invoice``          Vendor Bill
``in_refund``           Vendor Credit Note (a refund the vendor owes us)
``out_receipt``         Sales Receipt
``in_receipt``          Purchase Receipt
``entry``               Manual / miscellaneous Journal Entry
======================  =========================================================

The two axes that matter for the user's request are:

* **customer side**  -> ``out_invoice``, ``out_refund``, ``out_receipt``
* **vendor side**    -> ``in_invoice``, ``in_refund``, ``in_receipt``
* **not a document** -> ``entry`` (captured in journal entries)

Odoo 18 ``account.payment`` is a 2x2 matrix on ``payment_type``
(inbound / outbound) x ``partner_type`` (customer / supplier), plus an
``internal`` payment type which is a bank/ cash transfer with no counterparty.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# --------------------------------------------------------------------------- #
# account.move.move_type constants
# --------------------------------------------------------------------------- #
MOVE_TYPE_CUSTOMER_INVOICE = "out_invoice"
MOVE_TYPE_CUSTOMER_REFUND = "out_refund"
MOVE_TYPE_VENDOR_BILL = "in_invoice"
MOVE_TYPE_VENDOR_REFUND = "in_refund"
MOVE_TYPE_CUSTOMER_RECEIPT = "out_receipt"
MOVE_TYPE_VENDOR_RECEIPT = "in_receipt"
MOVE_TYPE_JOURNAL_ENTRY = "entry"

#: Ordered bucket -> move_type(s).  Order matters: it drives the export order
#: and the order buckets are presented in ``list_financial_buckets``.
MOVE_TYPE_BUCKETS: dict[str, list[str]] = {
    "customer_invoices": [MOVE_TYPE_CUSTOMER_INVOICE],
    "customer_refunds": [MOVE_TYPE_CUSTOMER_REFUND],
    "vendor_bills": [MOVE_TYPE_VENDOR_BILL],
    "vendor_refunds": [MOVE_TYPE_VENDOR_REFUND],
    "customer_receipts": [MOVE_TYPE_CUSTOMER_RECEIPT],
    "vendor_receipts": [MOVE_TYPE_VENDOR_RECEIPT],
    "journal_entries": [MOVE_TYPE_JOURNAL_ENTRY],
}

#: ``account.payment`` bucket -> (payment_type, partner_type).  ``None`` means
#: "do not constrain this field" (used for internal transfers, where
#: ``partner_type`` is meaningless).
PAYMENT_TYPE_BUCKETS: dict[str, tuple[str, str | None]] = {
    "customer_payments_received": ("inbound", "customer"),
    "refunds_paid_to_customers": ("outbound", "customer"),
    "vendor_payments_made": ("outbound", "supplier"),
    "refunds_received_from_vendors": ("inbound", "supplier"),
    "internal_transfers": ("internal", None),
}

#: Buckets that represent money coming IN (for sign conventions in reporting).
_INBOUND_PAYMENT_BUCKETS = frozenset({"customer_payments_received", "refunds_received_from_vendors"})

# --------------------------------------------------------------------------- #
# Field lists for search_read
# --------------------------------------------------------------------------- #
INVOICE_FIELDS: tuple[str, ...] = (
    "id",
    "name",                # e.g. INV/2030/0001
    "ref",                 # vendor/customer reference
    "move_type",
    "state",               # draft / posted / cancel
    "payment_state",       # not_paid / partial / paid / in_payment / reversed
    "partner_id",
    "invoice_date",
    "invoice_date_due",
    "invoice_payment_term_id",
    "amount_untaxed",
    "amount_tax",
    "amount_total",
    "amount_residual",     # still owed (positive on a receivable)
    "amount_paid",
    "amount_residual_signed",
    "amount_total_signed",  # sign-aware total: negative on a credit note
    "partner_credit",       # customer's credit balance
    "currency_id",
    "company_id",
    "journal_id",
    "payment_reference",
    "narration",
    "user_id",
    "invoice_origin",
    "invoice_line_ids",
    "matched_payment_ids",
    "reconciled_payment_ids",
    "has_reconciled_entries",
)

PAYMENT_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "payment_type",        # inbound / outbound / internal
    "partner_type",       # customer / supplier
    "partner_id",
    "amount",
    "amount_signed",            # signed amount (negative when money leaves)
    "amount_company_currency_signed",  # amount in the company currency
    "currency_id",
    "company_currency_id",
    "date",                # accounting date
    "cheque_payment_date", # bank / cheque date
    "payment_reference",
    "real_estate_ref",     # unit / project reference used by Parkgroup
    "journal_id",
    "company_id",
    "move_id",             # the generated journal entry
    "state",
    "is_reconciled",
    "is_matched",
    "reconciled_invoice_ids",
    "reconciled_bill_ids",
    "reconciled_invoices_type",
    "amount_available_for_refund",
)

MOVE_LINE_FIELDS: tuple[str, ...] = (
    "id",
    "move_id",
    "move_type",
    "name",                # the line label
    "date",
    "account_id",
    "partner_id",
    "journal_id",
    "debit",
    "credit",
    "balance",             # debit - credit in company currency
    "amount_currency",     # signed amount in the line currency
    "amount_residual",
    "currency_id",
    "company_id",
    "reconciled",
    "full_reconcile_id",
    "analytic_distribution",
)

JOURNAL_FIELDS: tuple[str, ...] = (
    "id",
    "code",
    "name",
    "type",                # sale / purchase / bank / cash / general
    "company_id",
    "currency_id",
    "active",
)

PARTNER_FIELDS: tuple[str, ...] = (
    "id",
    "name",
    "email",
    "phone",
    "mobile",
    "vat",
    "country_id",
    "company_id",
    "customer_rank",
    "supplier_rank",
    "is_company",
    "active",
)

ACCOUNT_FIELDS: tuple[str, ...] = (
    "id",
    "code",
    "code_store",
    "name",
    "account_type",
    "internal_group",
    "reconcile",
    "company_ids",         # many2many in Odoo 18, not company_id
    "company_currency_id",
    "currency_id",
)

# --------------------------------------------------------------------------- #
# Human readable labels
# --------------------------------------------------------------------------- #
_MOVE_LABELS: dict[str, str] = {
    MOVE_TYPE_CUSTOMER_INVOICE: "Customer Invoice",
    MOVE_TYPE_CUSTOMER_REFUND: "Customer Credit Note (Refund)",
    MOVE_TYPE_VENDOR_BILL: "Vendor Bill",
    MOVE_TYPE_VENDOR_REFUND: "Vendor Credit Note (Refund)",
    MOVE_TYPE_CUSTOMER_RECEIPT: "Sales Receipt",
    MOVE_TYPE_VENDOR_RECEIPT: "Purchase Receipt",
    MOVE_TYPE_JOURNAL_ENTRY: "Journal Entry (Manual)",
}

_PAYMENT_LABELS: dict[str, str] = {
    "customer_payments_received": "Customer Payment Received",
    "refunds_paid_to_customers": "Refund Paid to Customer",
    "vendor_payments_made": "Vendor Payment Made",
    "refunds_received_from_vendors": "Refund Received from Vendor",
    "internal_transfers": "Internal Bank/Cash Transfer",
}


def human_bucket(move_type: str | None) -> str:
    """Readable label for an ``account.move.move_type`` value."""
    if not move_type:
        return "Unknown"
    return _MOVE_LABELS.get(move_type, str(move_type))


def human_payment_bucket(payment_type: str | None, partner_type: str | None) -> str:
    """Readable label for an ``account.payment`` payment_type/partner_type pair."""
    key = _payment_bucket(payment_type, partner_type)
    return _PAYMENT_LABELS.get(key, "Unclassified")


def _payment_bucket(payment_type: str | None, partner_type: str | None) -> str | None:
    for bucket, (ptype, partner) in PAYMENT_TYPE_BUCKETS.items():
        if ptype != payment_type:
            continue
        if partner is None:
            return bucket
        if partner == partner_type:
            return bucket
    return None


# --------------------------------------------------------------------------- #
# Domain builders
# --------------------------------------------------------------------------- #
def _date_clause(field: str, date_from: str | None, date_to: str | None) -> list[Any]:
    """Inclusive ``>= from`` / ``<= to`` clauses on ``field``.

    Emits flat ``(field, op, value)`` tuples to match the rest of the domain
    builders, so callers can compare clauses directly.
    """
    domain: list[Any] = []
    if date_from:
        domain.append((field, ">=", date_from))
    if date_to:
        domain.append((field, "<=", date_to))
    return domain


def date_field_for_bucket(bucket: str) -> str:
    """Which date column a bucket is filtered on.

    Journal entries (``move_type = 'entry'``) have **no** ``invoice_date`` - it
    is ``False`` - so date filtering them on that column silently returns
    nothing.  Every other move type is an invoice/bill and is filtered on
    ``invoice_date``.
    """
    return "date" if bucket == "journal_entries" else "invoice_date"


def _validate_bucket(bucket: str, valid: Iterable[str]) -> None:
    if bucket not in valid:
        raise ValueError(
            f"Unknown bucket {bucket!r}. Valid buckets: {sorted(valid)}"
        )


def domain_for_move_bucket(
    bucket: str,
    date_from: str | None = None,
    date_to: str | None = None,
    partner_id: int | None = None,
    journal_id: int | None = None,
    company_id: int | None = None,
    payment_state: str | None = None,
    include_draft: bool = True,
    include_cancel: bool = False,
) -> list[Any]:
    """Build an ``account.move`` domain for one bucket.

    Args:
        bucket: key of :data:`MOVE_TYPE_BUCKETS`.
        date_from: inclusive start date, ``YYYY-MM-DD``.
        date_to: inclusive end date, ``YYYY-MM-DD``.
        partner_id: restrict to one ``res.partner``.
        journal_id: restrict to one ``account.journal``.
        company_id: restrict to one ``res.company`` (multi-company safe).
        payment_state: restrict to e.g. ``not_paid``, ``partial``, ``paid``.
        include_draft: when ``False``, only posted moves are returned.
        include_cancel: when ``False`` (default), cancelled moves are excluded.

    Returns:
        An Odoo domain list suitable for ``search_read`` / ``search_count``.
    """
    _validate_bucket(bucket, MOVE_TYPE_BUCKETS)
    move_types = MOVE_TYPE_BUCKETS[bucket]

    domain: list[Any] = [("move_type", "in", list(move_types))]
    domain += _date_clause(date_field_for_bucket(bucket), date_from, date_to)

    if partner_id:
        domain += [("partner_id", "=", partner_id)]
    if journal_id:
        domain += [("journal_id", "=", journal_id)]
    if company_id:
        domain += [("company_id", "=", company_id)]
    if payment_state:
        domain += [("payment_state", "=", payment_state)]

    if not include_draft:
        domain += [("state", "=", "posted")]
    if not include_cancel:
        domain += [("state", "not in", ["cancel"])]
    return domain


def domain_for_payment_bucket(
    bucket: str,
    date_from: str | None = None,
    date_to: str | None = None,
    partner_id: int | None = None,
    journal_id: int | None = None,
    company_id: int | None = None,
    include_draft: bool = True,
) -> list[Any]:
    """Build an ``account.payment`` domain for one bucket.

    Payments always filter on ``date`` (their accounting date); ``payment_date``
    is the bank/cheque date and is often empty on drafts.
    """
    _validate_bucket(bucket, PAYMENT_TYPE_BUCKETS)
    payment_type, partner_type = PAYMENT_TYPE_BUCKETS[bucket]

    domain: list[Any] = [("payment_type", "=", payment_type)]
    # partner_type is deliberately NOT constrained for internal transfers.
    if partner_type is not None:
        domain += [("partner_type", "=", partner_type)]

    domain += _date_clause("date", date_from, date_to)

    if partner_id:
        domain += [("partner_id", "=", partner_id)]
    if journal_id:
        domain += [("journal_id", "=", journal_id)]
    if company_id:
        domain += [("company_id", "=", company_id)]
    if not include_draft:
        domain += [("state", "not in", ["draft", "cancel"])]
    return domain


def domain_for_journal_entries(
    date_from: str | None = None,
    date_to: str | None = None,
    journal_id: int | None = None,
    company_id: int | None = None,
    partner_id: int | None = None,
    include_draft: bool = True,
    include_cancel: bool = False,
) -> list[Any]:
    """Convenience wrapper for the ``journal_entries`` bucket."""
    return domain_for_move_bucket(
        "journal_entries",
        date_from=date_from,
        date_to=date_to,
        partner_id=partner_id,
        journal_id=journal_id,
        company_id=company_id,
        include_draft=include_draft,
        include_cancel=include_cancel,
    )


def domain_for_journal_entry_lines(
    date_from: str | None = None,
    date_to: str | None = None,
    journal_id: int | None = None,
    company_id: int | None = None,
    partner_id: int | None = None,
    account_id: int | None = None,
    include_draft: bool = True,
    include_cancel: bool = False,
) -> list[Any]:
    """Build an ``account.move.line`` domain for miscellaneous journal entries.

    ``account.move.line`` has **no** ``state`` field - the parent move's state is
    exposed as ``parent_state``. Reusing an ``account.move`` domain here raises
    ``Invalid field account.move.line.state``.
    """
    domain: list[Any] = [("move_type", "=", MOVE_TYPE_JOURNAL_ENTRY)]
    domain += _date_clause("date", date_from, date_to)

    if journal_id:
        domain += [("journal_id", "=", journal_id)]
    if company_id:
        domain += [("company_id", "=", company_id)]
    if partner_id:
        domain += [("partner_id", "=", partner_id)]
    if account_id:
        domain += [("account_id", "=", account_id)]

    if not include_draft:
        domain += [("parent_state", "=", "posted")]
    if not include_cancel:
        domain += [("parent_state", "not in", ["cancel"])]
    return domain


def domain_for_move_lines(
    date_from: str | None = None,
    date_to: str | None = None,
    move_type: str | None = None,
    journal_id: int | None = None,
    company_id: int | None = None,
    partner_id: int | None = None,
    account_id: int | None = None,
) -> list[Any]:
    """Unfiltered ``account.move.line`` domain - the complete general ledger."""
    domain: list[Any] = []
    if move_type:
        domain += [("move_type", "=", move_type)]
    domain += _date_clause("date", date_from, date_to)
    if journal_id:
        domain += [("journal_id", "=", journal_id)]
    if company_id:
        domain += [("company_id", "=", company_id)]
    if partner_id:
        domain += [("partner_id", "=", partner_id)]
    if account_id:
        domain += [("account_id", "=", account_id)]
    return domain


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def _move_bucket(move_type: str | None) -> str | None:
    if not move_type:
        return None
    for bucket, types in MOVE_TYPE_BUCKETS.items():
        if move_type in types:
            return bucket
    return None


def classify_move(row: Mapping[str, Any]) -> dict[str, Any]:
    """Classify an ``account.move`` row into a bucket and reporting facets.

    Never raises: an unknown or missing ``move_type`` yields ``bucket=None``.
    """
    move_type = row.get("move_type")
    bucket = _move_bucket(move_type)

    is_refund = move_type in (MOVE_TYPE_CUSTOMER_REFUND, MOVE_TYPE_VENDOR_REFUND)
    if move_type in (MOVE_TYPE_CUSTOMER_INVOICE, MOVE_TYPE_CUSTOMER_REFUND,
                     MOVE_TYPE_CUSTOMER_RECEIPT):
        counterparty_type = "customer"
    elif move_type in (MOVE_TYPE_VENDOR_BILL, MOVE_TYPE_VENDOR_REFUND,
                       MOVE_TYPE_VENDOR_RECEIPT):
        counterparty_type = "supplier"
    elif move_type == MOVE_TYPE_JOURNAL_ENTRY:
        counterparty_type = "none"
    else:
        counterparty_type = "none"

    if bucket in ("customer_invoices", "vendor_bills", "customer_receipts",
                  "vendor_receipts"):
        direction = "inbound"          # money owed to us / asset acquired
    elif bucket in ("customer_refunds", "vendor_refunds"):
        direction = "outbound"
    else:
        direction = "none"

    return {
        "bucket": bucket,
        "label": human_bucket(move_type),
        "move_type": move_type,
        "direction": direction,
        "is_refund": is_refund,
        "counterparty_type": counterparty_type,
    }


def classify_payment(row: Mapping[str, Any]) -> dict[str, Any]:
    """Classify an ``account.payment`` row. Never raises."""
    payment_type = row.get("payment_type")
    partner_type = row.get("partner_type")
    bucket = _payment_bucket(payment_type, partner_type)

    if payment_type == "internal":
        direction = "none"
    elif bucket in _INBOUND_PAYMENT_BUCKETS:
        direction = "inbound"
    elif bucket:
        direction = "outbound"
    else:
        direction = "none"

    is_refund = bucket in ("refunds_paid_to_customers", "refunds_received_from_vendors")
    if partner_type in ("customer", "supplier"):
        counterparty_type = partner_type
    else:
        counterparty_type = "none"

    return {
        "bucket": bucket,
        "label": human_payment_bucket(payment_type, partner_type),
        "payment_type": payment_type,
        "partner_type": partner_type,
        "direction": direction,
        "is_refund": is_refund,
        "counterparty_type": counterparty_type,
    }


#: Which Odoo model backs each export dataset.
DATASET_MODEL: dict[str, str] = {
    **{bucket: "account.move" for bucket in MOVE_TYPE_BUCKETS},
    **{bucket: "account.payment" for bucket in PAYMENT_TYPE_BUCKETS},
    "partners": "res.partner",
    "journals": "account.journal",
    "accounts": "account.account",
    "journal_entry_lines": "account.move.line",
}


__all__ = [
    "MOVE_TYPE_CUSTOMER_INVOICE",
    "MOVE_TYPE_CUSTOMER_REFUND",
    "MOVE_TYPE_VENDOR_BILL",
    "MOVE_TYPE_VENDOR_REFUND",
    "MOVE_TYPE_CUSTOMER_RECEIPT",
    "MOVE_TYPE_VENDOR_RECEIPT",
    "MOVE_TYPE_JOURNAL_ENTRY",
    "MOVE_TYPE_BUCKETS",
    "PAYMENT_TYPE_BUCKETS",
    "INVOICE_FIELDS",
    "PAYMENT_FIELDS",
    "MOVE_LINE_FIELDS",
    "JOURNAL_FIELDS",
    "PARTNER_FIELDS",
    "ACCOUNT_FIELDS",
    "DATASET_MODEL",
    "human_bucket",
    "human_payment_bucket",
    "date_field_for_bucket",
    "domain_for_move_bucket",
    "domain_for_payment_bucket",
    "domain_for_journal_entries",
    "domain_for_journal_entry_lines",
    "domain_for_move_lines",
    "classify_move",
    "classify_payment",
]