"""FastMCP server exposing Parkgroup Real Estate accounting data from Odoo 18.

Why this is an external (stdio) MCP server
-----------------------------------------
Odoo 18 has **no** native MCP endpoint.  Odoo's built-in ``/mcp`` server arrived
in v19/v20, and the ``/json/2`` external API is likewise 19+.  On Odoo Online it
is additionally impossible to install third-party modules such as ``muk_mcp``
or ``odoo_ai_mcp``, which are the usual way to bolt an ``/mcp`` endpoint onto
v18.  So the only supported architecture on ``pgre.odoo.com`` is an MCP server
that runs locally and talks to the Odoo 18 external API (JSON-RPC, with an
automatic XML-RPC fallback) using a normal Odoo API key.

What this exposes
-----------------
The accounting data the user asked for, split by Odoo's own semantics so
nothing has to be inferred:

* customer invoices, customer refunds (credit notes), sales receipts
* vendor bills, vendor refunds (credit notes), purchase receipts
* customer payments received, refunds paid to customers,
  vendor payments made, refunds received from vendors, internal transfers
* miscellaneous journal entries plus their individual journal lines
* partners and journals as supporting reference data

Importing this module performs **no** network access; the authenticated client
is created lazily on first tool call.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Iterable, Sequence

from fastmcp import FastMCP

from accounting import (  # noqa: F401  (re-exported for tool authors)
    ACCOUNT_FIELDS,
    DATASET_MODEL,
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
    domain_for_move_bucket,
    domain_for_payment_bucket,
    human_bucket,
    human_payment_bucket,
)
from pgre_client import OdooAuthError, OdooClient, OdooError, get_client

log = logging.getLogger("pgre.mcp")

mcp = FastMCP("pgre-odoo")

DEFAULT_LIMIT = 200
MAX_LIMIT = 2000


# --------------------------------------------------------------------------- #
# Plumbing
# --------------------------------------------------------------------------- #
def _client() -> OdooClient:
    """Return the cached authenticated client, or raise a friendly error."""
    try:
        return get_client()
    except OdooAuthError as exc:
        raise RuntimeError(
            "Not authenticated with Odoo. Generate an Odoo API key "
            "(My Profile -> Account Security -> New API Key; the key is 40 "
            "characters) and export it as PGRE_KEY, plus PGRE_LOGIN and "
            f"PGRE_URL. Original error: {exc}"
        ) from exc
    except OdooError as exc:
        raise RuntimeError(f"Odoo connection problem: {exc}") from exc


def _normalise(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten Odoo relational tuples into readable values, keeping the ids.

    Odoo returns many2one values as ``[id, display_name]``.  We keep the raw id
    under ``<field>_id`` and add a readable ``<field>_name`` so downstream
    exports and reports never have to re-resolve names.
    """
    out: dict[str, Any] = {}
    for key, value in row.items():
        if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], int):
            rel_id, display = value
            out[key] = rel_id
            out[f"{key}_name"] = display
        elif isinstance(value, list):
            out[key] = value
        else:
            out[key] = value
    return out


def _fetch(
    model: str,
    domain: list[Any],
    fields: Sequence[str],
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    order: str | None = "id asc",
) -> dict[str, Any]:
    """Page through a model and return ``{rows, count, returned, offset}``.

    ``count`` is the full match count (not just this page) so callers can see
    how much more there is, and ``truncated`` tells them the page cut off.
    """
    client = _client()
    capped = max(1, min(int(limit), MAX_LIMIT))
    total = client.search_count(model, domain)
    rows: list[dict[str, Any]] = []
    if total and offset < total:
        skipped = 0
        for raw in client.iter_search_read(model, domain, list(fields), order=order):
            if skipped < offset:
                skipped += 1
                continue
            if len(rows) >= capped:
                break
            rows.append(raw)
    return {
        "model": model,
        "rows": rows,
        "count": total,
        "returned": len(rows),
        "offset": offset,
        "truncated": offset + len(rows) < total,
    }


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
@mcp.tool
def odoo_whoami() -> dict[str, Any]:
    """Connection diagnostics: URL, database, uid, transport, server version, user."""
    return _client().about()


@mcp.tool
def list_financial_buckets() -> dict[str, Any]:
    """List every financial bucket this server understands and how many records exist.

    Start here: it tells you whether the database has customer invoices, vendor
    bills, refunds, payments or journal entries before you query anything.
    """
    client = _client()
    move_counts: dict[str, int] = {}
    for bucket in MOVE_TYPE_BUCKETS:
        domain = domain_for_move_bucket(bucket, include_draft=True, include_cancel=False)
        move_counts[bucket] = client.search_count("account.move", domain)

    payment_counts: dict[str, int] = {}
    for bucket in PAYMENT_TYPE_BUCKETS:
        domain = domain_for_payment_bucket(bucket, include_draft=True)
        payment_counts[bucket] = client.search_count("account.payment", domain)

    return {
        "about": client.about(),
        "move_buckets": {
            bucket: {
                "label": human_bucket(MOVE_TYPE_BUCKETS[bucket][0]),
                "move_types": MOVE_TYPE_BUCKETS[bucket],
                "model": "account.move",
                "count": move_counts[bucket],
            }
            for bucket in MOVE_TYPE_BUCKETS
        },
        "payment_buckets": {
            bucket: {
                "label": human_payment_bucket(*PAYMENT_TYPE_BUCKETS[bucket]),
                "payment_type": PAYMENT_TYPE_BUCKETS[bucket][0],
                "partner_type": PAYMENT_TYPE_BUCKETS[bucket][1],
                "model": "account.payment",
                "count": payment_counts[bucket],
            }
            for bucket in PAYMENT_TYPE_BUCKETS
        },
        "notes": {
            "date_field": "invoice_date for invoice/bill/receipt buckets; "
                          "date for journal_entries",
            "drafts": "counts above exclude cancelled moves but include drafts",
            "dataset_model": DATASET_MODEL,
        },
    }


@mcp.tool
def get_invoices(
    bucket: str = "customer_invoices",
    date_from: str | None = None,
    date_to: str | None = None,
    partner_id: int | None = None,
    journal_id: int | None = None,
    company_id: int | None = None,
    payment_state: str | None = None,
    include_draft: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Get invoices / bills / credit notes from the `account.move` model.

    Args:
        bucket: one of `customer_invoices`, `customer_refunds`, `vendor_bills`,
            `vendor_refunds`, `customer_receipts`, `vendor_receipts`,
            `journal_entries`.  `out_refund` = customer refund,
            `in_refund` = vendor refund.
        date_from: inclusive start date, `YYYY-MM-DD` (invoice_date, or `date`
            for journal_entries).
        date_to: inclusive end date, `YYYY-MM-DD`.
        partner_id: restrict to one `res.partner` id.
        journal_id: restrict to one `account.journal` id.
        company_id: restrict to one `res.company` id.
        payment_state: e.g. `not_paid`, `partial`, `paid`.
        include_draft: include draft moves (default False = posted only).
        limit: max rows in this page (hard cap 2000).
        offset: row offset for paging.
    """
    domain = domain_for_move_bucket(
        bucket,
        date_from=date_from,
        date_to=date_to,
        partner_id=partner_id,
        journal_id=journal_id,
        company_id=company_id,
        payment_state=payment_state,
        include_draft=include_draft,
    )
    result = _fetch("account.move", domain, INVOICE_FIELDS, limit=limit, offset=offset)
    result["bucket"] = bucket
    result["classification"] = [classify_move(r) for r in result["rows"]]
    return result


@mcp.tool
def get_payments(
    bucket: str = "customer_payments_received",
    date_from: str | None = None,
    date_to: str | None = None,
    partner_id: int | None = None,
    journal_id: int | None = None,
    company_id: int | None = None,
    include_draft: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Get payments / refunds from the `account.payment` model.

    The bucket maps Odoo's 2x2 matrix of `payment_type` (inbound / outbound)
    against `partner_type` (customer / supplier):

    - `customer_payments_received`  - money in from customers
    - `refunds_paid_to_customers`   - money out back to customers
    - `vendor_payments_made`        - money out to vendors
    - `refunds_received_from_vendors` - money in back from vendors
    - `internal_transfers`          - bank <-> cash, no counterparty

    Args mirror `get_invoices`; payments are always filtered on `date`.
    """
    domain = domain_for_payment_bucket(
        bucket,
        date_from=date_from,
        date_to=date_to,
        partner_id=partner_id,
        journal_id=journal_id,
        company_id=company_id,
        include_draft=include_draft,
    )
    result = _fetch("account.payment", domain, PAYMENT_FIELDS, limit=limit, offset=offset)
    result["bucket"] = bucket
    result["classification"] = [classify_payment(r) for r in result["rows"]]
    return result


@mcp.tool
def get_journal_entries(
    date_from: str | None = None,
    date_to: str | None = None,
    journal_id: int | None = None,
    company_id: int | None = None,
    partner_id: int | None = None,
    include_draft: bool = False,
    include_lines: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Get miscellaneous journal entries (`move_type = 'entry'`).

    These are the transactions that are *not* invoices, bills or payments -
    accruals, reclassifications, escrow movements, manual corrections - and are
    therefore the "identify it in the journal entries" case.

    Args:
        include_lines: also return each entry's `line_ids` (account code/name,
            partner, debit, credit, balance).  This is an **extra RPC call per
            page** and can be very heavy on large result sets - only enable it
            when you actually need the line breakdown, and prefer paging with
            a smaller `limit`.  When the page holds more than 200 entries the
            response is flagged with `lines_truncated` instead of silently
            loading thousands of lines.
        All other args mirror `get_invoices`.  Journal entries are filtered on
        `date`, never `invoice_date` (which is empty for them).
    """
    domain = domain_for_journal_entries(
        date_from=date_from,
        date_to=date_to,
        journal_id=journal_id,
        company_id=company_id,
        partner_id=partner_id,
        include_draft=include_draft,
    )
    result = _fetch("account.move", domain, INVOICE_FIELDS, limit=limit, offset=offset)
    result["bucket"] = "journal_entries"

    if include_lines and result["rows"]:
        client = _client()
        rows = result["rows"]
        flagged = False
        if len(rows) > 200:
            flagged = True
            rows = rows[:200]
        move_ids = [r["id"] for r in rows]
        lines: list[dict[str, Any]] = []
        # One search_read over account.move.line for the whole page, rather than
        # one read() per move: Odoo Online rate-limits aggressively.
        if move_ids:
            line_domain = [["move_id", "in", move_ids]]
            for raw in client.iter_search_read(
                "account.move.line", line_domain, list(MOVE_LINE_FIELDS), order="id asc"
            ):
                lines.append(_normalise(raw))
        result["rows"] = [{**_normalise(r), "lines": [ln for ln in lines if ln["move_id"] == r["id"]]}
                          for r in rows]
        result["line_count"] = len(lines)
        if flagged:
            result["lines_truncated"] = (
                f"Page contained {result['count']} entries; only the first 200 "
                "had their lines loaded. Page with a smaller `limit` for full detail."
            )
    return result


@mcp.tool
def get_move_lines(
    date_from: str | None = None,
    date_to: str | None = None,
    account_id: int | None = None,
    journal_id: int | None = None,
    partner_id: int | None = None,
    move_type: str | None = None,
    company_id: int | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    """Get individual journal entry lines from `account.move.line`.

    This is the flat, GL-level view: one row per accounting line with account
    code/name, partner, debit, credit and balance.  Use it to drill into any
    document, reconcile, or run custom reporting that the document views cannot
    answer.

    Args:
        move_type: optional `account.move.move_type` filter, e.g. `entry`,
            `out_invoice`, `in_invoice`.
        Other args are direct column filters; `limit` defaults to 500 (cap 2000).
    """
    domain: list[Any] = []
    if date_from:
        domain += [("date", ">=", date_from)]
    if date_to:
        domain += [("date", "<=", date_to)]
    if account_id:
        domain += [("account_id", "=", account_id)]
    if journal_id:
        domain += [("journal_id", "=", journal_id)]
    if partner_id:
        domain += [("partner_id", "=", partner_id)]
    if move_type:
        domain += [("move_type", "=", move_type)]
    if company_id:
        domain += [("company_id", "=", company_id)]

    result = _fetch("account.move.line", domain, MOVE_LINE_FIELDS, limit=limit, offset=offset)
    result["rows"] = [_normalise(r) for r in result["rows"]]
    return result


@mcp.tool
def list_journals(company_id: int | None = None, include_archived: bool = False) -> dict[str, Any]:
    """List accounting journals (sales, purchase, bank, cash, general)."""
    domain: list[Any] = []
    if company_id:
        domain += [("company_id", "=", company_id)]
    if not include_archived:
        domain += [("active", "=", True)]
    client = _client()
    rows = list(client.iter_search_read("account.journal", domain, list(JOURNAL_FIELDS), order="code asc"))
    return {"rows": [_normalise(r) for r in rows], "count": len(rows)}


@mcp.tool
def list_partners(
    limit: int = 100,
    offset: int = 0,
    search: str | None = None,
    supplier_only: bool = False,
    customer_only: bool = False,
) -> dict[str, Any]:
    """List partners (customers and/or vendors).

    Args:
        search: case-insensitive match on name, email or phone.
        supplier_only: only vendors (`supplier_rank > 0`).
        customer_only: only customers (`customer_rank > 0`).
    """
    domain: list[Any] = [("active", "=", True)]
    if search:
        domain += [
            "|", "|",
            ("name", "ilike", search),
            ("email", "ilike", search),
            ("phone", "ilike", search),
        ]
    if supplier_only:
        domain += [("supplier_rank", ">", 0)]
    if customer_only:
        domain += [("customer_rank", ">", 0)]
    result = _fetch("res.partner", domain, PARTNER_FIELDS, limit=limit, offset=offset)
    result["rows"] = [_normalise(r) for r in result["rows"]]
    return result


@mcp.tool
def financial_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    include_draft: bool = False,
    company_id: int | None = None,
) -> dict[str, Any]:
    """Aggregate counts and totals per bucket, **split by currency**.

    Amounts are never summed across currencies - each currency gets its own
    `count` / `total_*` entry, which is what makes this safe on a
    multi-currency ledger (AED books with USD property sales).
    """
    client = _client()
    move_summary: dict[str, Any] = {}
    for bucket in MOVE_TYPE_BUCKETS:
        domain = domain_for_move_bucket(bucket, date_from=date_from, date_to=date_to,
                                        company_id=company_id, include_draft=include_draft)
        per_currency: dict[str, dict[str, float]] = {}
        for raw in client.iter_search_read(
            "account.move", domain,
            ["amount_total", "amount_residual", "amount_paid", "currency_id", "state"],
            order="id asc",
        ):
            row = _normalise(raw)
            code = str(row.get("currency_id_name") or "?")
            agg = per_currency.setdefault(code, {"count": 0, "total": 0.0,
                                                 "residual": 0.0, "paid": 0.0})
            agg["count"] += 1
            agg["total"] += float(row.get("amount_total") or 0.0)
            agg["residual"] += float(row.get("amount_residual") or 0.0)
            agg["paid"] += float(row.get("amount_paid") or 0.0)
        move_summary[bucket] = {
            "label": human_bucket(MOVE_TYPE_BUCKETS[bucket][0]),
            "model": "account.move",
            "currencies": per_currency,
        }

    payment_summary: dict[str, Any] = {}
    for bucket in PAYMENT_TYPE_BUCKETS:
        domain = domain_for_payment_bucket(bucket, date_from=date_from, date_to=date_to,
                                           company_id=company_id, include_draft=include_draft)
        per_currency = {}
        for raw in client.iter_search_read(
            "account.payment", domain,
            ["amount", "amount_company_currency_signed", "currency_id"],
            order="id asc",
        ):
            row = _normalise(raw)
            code = str(row.get("currency_id_name") or "?")
            agg = per_currency.setdefault(code, {"count": 0, "amount": 0.0,
                                                 "amount_company_currency": 0.0})
            agg["count"] += 1
            agg["amount"] += float(row.get("amount") or 0.0)
            agg["amount_company_currency"] += float(
                row.get("amount_company_currency_signed") or 0.0)
        payment_summary[bucket] = {
            "label": human_payment_bucket(*PAYMENT_TYPE_BUCKETS[bucket]),
            "model": "account.payment",
            "currencies": per_currency,
        }

    return {
        "date_from": date_from,
        "date_to": date_to,
        "include_draft": include_draft,
        "company_id": company_id,
        "about": client.about(),
        "moves": move_summary,
        "payments": payment_summary,
        "note": "Amounts are grouped by currency and must not be added together "
                "across different currency keys.",
    }


@mcp.tool
def find_unpaid(
    date_from: str | None = None,
    date_to: str | None = None,
    include_draft: bool = False,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    """Find invoices and bills still carrying a balance (`amount_residual > 0`).

    Returns `payment_state`, `invoice_date_due` and currency so receivables /
    payables aging can be computed client-side.  Receivables and payables are
    reported in separate sections because they are owed in opposite directions.
    """
    out: dict[str, Any] = {}
    for section, buckets in (
        ("receivables", ["customer_invoices", "customer_receipts"]),
        ("payables", ["vendor_bills", "vendor_receipts"]),
    ):
        rows: list[dict[str, Any]] = []
        for bucket in buckets:
            domain = domain_for_move_bucket(bucket, date_from=date_from, date_to=date_to,
                                            include_draft=include_draft)
            domain += [("amount_residual", ">", 0)]
            page = _fetch("account.move", domain, INVOICE_FIELDS, limit=limit, offset=offset)
            for raw in page["rows"]:
                row = _normalise(raw)
                row["classification"] = classify_move(raw)
                rows.append(row)
        rows.sort(key=lambda r: (str(r.get("invoice_date_due") or "9999"), r.get("id", 0)))
        out[section] = {"count": len(rows), "rows": rows}
    out["note"] = "amount_residual > 0. For credit notes the residual is negative; " \
                  "use the customer_refunds / vendor_refunds buckets for those."
    return out


# --------------------------------------------------------------------------- #
# Resource
# --------------------------------------------------------------------------- #
@mcp.resource("odoo://buckets")
def buckets_resource() -> str:
    """JSON description of every financial bucket and its record count."""
    return json.dumps(list_financial_buckets(), indent=2, default=str)


def main() -> None:  # pragma: no cover - process entry point
    logging.basicConfig(level=logging.INFO, stream=__import__("sys").stderr)
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()