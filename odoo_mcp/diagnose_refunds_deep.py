"""Find refunds that were recorded as manual journal entries instead of credit notes.

The database contains exactly **one** ``out_refund`` (not posted) and zero
``in_refund``.  But it holds 8,771 miscellaneous journal entries.  If the
business recorded refunds by hand, they will not appear in any credit-note
bucket - they will be a **debit to a revenue/income account**, because giving
money back is contra-revenue.

This finds those entries so refunds can be identified from journal entries, as
the user requested.
"""

from __future__ import annotations

from collections import defaultdict

from pgre_client import OdooClient, OdooError

REVENUE_TYPES = ("income", "income_other", "other_income")


def main() -> int:
    client = OdooClient()

    print("=" * 78)
    print("A. REVENUE / INCOME ACCOUNTS in the chart")
    print("=" * 78)
    revenue_ids = client.search_ids("account.account", [
        ("account_type", "in", list(REVENUE_TYPES))], limit=0)
    print(f"  revenue-type accounts: {len(revenue_ids):,}")
    for acc in client.read("account.account", revenue_ids, ["code", "name", "account_type"])[:40]:
        print(f"    {acc.get('code')!s:<12} {acc.get('name')!s:<50} {acc.get('account_type')}")

    print()
    print("=" * 78)
    print("B. DEBITS against revenue  (contra-revenue == money given back)")
    print("=" * 78)
    domain = [("account_id", "in", revenue_ids), ("debit", ">", 0)]
    total = client.search_count("account.move.line", domain)
    print(f"  revenue lines with a DEBIT balance: {total:,}")
    if not total:
        print("  -> No contra-revenue entries. Refunds are NOT recorded in journal entries.")
        return 0

    # Pull the offending lines and roll them up by journal entry.
    lines = list(client.iter_search_read("account.move.line", domain, [
        "move_id", "date", "name", "account_id", "partner_id", "debit",
        "credit", "balance", "journal_id"], page=500, order="date desc"))

    by_move: dict[int, dict] = {}
    for ln in lines:
        mid = ln["move_id"][0] if isinstance(ln.get("move_id"), (list, tuple)) else ln.get("move_id")
        rec = by_move.setdefault(mid, {"lines": [], "date": ln.get("date"),
                                       "journal": ln.get("journal_id"),
                                       "partner": None, "name": None, "total": 0.0})
        rec["lines"].append(ln)
        rec["total"] += float(ln.get("debit") or 0)
        if ln.get("partner_id") and not rec["partner"]:
            rec["partner"] = ln["partner_id"][1]
        if not rec["name"]:
            rec["name"] = ln.get("name")

    moves = client.read("account.move", list(by_move.keys()),
                        ["name", "move_type", "state", "ref", "narration", "invoice_date"])
    move_by_id = {m["id"]: m for m in moves}

    print(f"  distinct journal entries involved: {len(by_move):,}")
    print()
    print(f"  {'entry':<22}{'date':<12}{'type':<7}{'state':<9}{'contra revenue':>16}  partner")
    print("  " + "-" * 96)
    for mid, rec in sorted(by_move.items(), key=lambda kv: str(kv[1]["date"]), reverse=True):
        m = move_by_id.get(mid, {})
        partner = rec["partner"] or (m.get("name") or "")[:0]
        print(f"  {str(m.get('name') or mid):<22}{str(rec['date'] or ''):<12}"
              f"{str(m.get('move_type')):<7}{str(m.get('state')):<9}"
              f"{rec['total']:>16,.2f}  {str(partner)[:30]}")

    print()
    print("=" * 78)
    print("C. Search for refund wording in references / narration")
    print("=" * 78)
    for keyword in ("refund", "credit note", "cn/", "return", "reversal", "rebate", "discount"):
        # Prefix-OR notation: N conditions need N-1 leading '|' operators.
        try:
            n = client.search_count("account.move", [
                "|", "|", "|",
                ("ref", "ilike", keyword),
                ("narration", "ilike", keyword),
                ("name", "ilike", keyword),
                ("payment_reference", "ilike", keyword),
            ])
        except OdooError as exc:
            n = f"ERR {str(exc)[:70]}"
        print(f"  move references containing {keyword!r:<14} {n}")

    print()
    print("=" * 78)
    print("D. Outbound customer payments (money physically returned)")
    print("=" * 78)
    rows = client.search_read("account.payment",
                              [("payment_type", "=", "outbound")],
                              ["name", "date", "amount", "partner_type", "partner_id",
                               "payment_reference", "is_reconciled", "state"],
                              limit=50, order="date desc")
    print(f"  total outbound payments: {client.search_count('account.payment', [('payment_type','=','outbound')]):,}")
    for r in rows:
        print(f"  {str(r.get('name')):<18}{str(r.get('date')):<12}{r.get('amount')!s:>14} "
              f"{str(r.get('partner_type')):<11}{str((r.get('partner_id') or ['',''])[1])[:30]:<32}"
              f"ref={str(r.get('payment_reference'))[:24]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())