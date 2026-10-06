"""Print account.payment.term.line schema and the installment definitions.

`account.payment.term.line` uses ``payment_id`` as the back-reference to the
term (it was ``payment_term_id`` in older versions), so the previous probe
failed. This prints the real schema and then the line definitions per term.
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict

from pgre_client import OdooClient, OdooError

for _s in ("stdout", "stderr"):
    _st = getattr(sys, _s, None)
    if _st and hasattr(_st, "reconfigure"):
        try:
            _st.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main() -> int:
    c = OdooClient()
    fg = c.fields_get("account.payment.term.line", attributes=["type", "string", "relation"])
    print("=" * 100)
    print("account.payment.term.line SCHEMA")
    print("=" * 100)
    for k in sorted(fg):
        print(f"  {k:<28} {str(fg[k].get('type')):<12} "
              f"{str(fg[k].get('relation')):<26} {fg[k].get('string')}")

    parent = "payment_id" if "payment_id" in fg else "payment_term_id"
    print(f"\n  -> back-reference to the term is `{parent}`")

    lines = c.search_read("account.payment.term.line", [],
                          [parent, "value", "value_amount", "delay_type", "nb_days"],
                          limit=0, order="id asc")
    print()
    print("=" * 100)
    print(f"PAYMENT TERM LINES  ({len(lines)} total)")
    print("=" * 100)
    by_term: dict[int, list[dict]] = defaultdict(list)
    for ln in lines:
        by_term[(ln.get(parent) or [None])[0]].append(ln)

    terms = c.search_read("account.payment.term", [],
                          ["name", "company_id", "active", "payment_during_construction"],
                          limit=0, order="id asc")
    tname = {t["id"]: t["name"] for t in terms}
    tco = {t["id"]: (t.get("company_id") or [None, "-"])[1] for t in terms}
    tact = {t["id"]: t.get("active") for t in terms}

    print(f"  terms defined: {len(terms)}   terms with lines: {len(by_term)}")
    for tid in sorted(by_term):
        lns = by_term[tid]
        parts = []
        for ln in lns:
            val = ln.get("value")
            amt = ln.get("value_amount")
            if val == "percent":
                parts.append(f"{amt:g}%" if amt is not None else "?%")
            elif val == "balance":
                parts.append("balance")
            else:
                parts.append(f"+{amt:g}d" if amt is not None else str(val))
        seq = " ".join(parts)
        print(f"    id={tid:<5} {str(tname.get(tid))[:44]:<46} "
              f"{len(lns):>3} lines | {seq[:60]:<62} "
              f"co={str(tco.get(tid))[:30]}")

    # Which terms are actually used on invoices?
    print()
    print("=" * 100)
    print("TERMS ACTUALLY USED ON POSTED CUSTOMER INVOICES")
    print("=" * 100)
    groups = c.execute_kw("account.move", "read_group", [], {
        "domain": [("move_type", "=", "out_invoice"), ("state", "=", "posted")],
        "fields": ["invoice_payment_term_id"], "groupby": ["invoice_payment_term_id"],
        "lazy": False}) or []
    total_inv = sum((g.get("invoice_payment_term_id_count") or 0) for g in groups)
    print(f"  distinct terms used: {len(groups)}   invoices covered: {total_inv:,}")
    used_ids = {(g.get("invoice_payment_term_id") or [None])[0] for g in groups}
    for g in sorted(groups, key=lambda x: -(x.get("invoice_payment_term_id_count") or 0)):
        tid = (g.get("invoice_payment_term_id") or [None, "(none)"])[0]
        nm = (g.get("invoice_payment_term_id") or [None, "(none)"])[1]
        has = "has lines" if tid in by_term else "NO LINES"
        print(f"    {str(nm)[:48]:<50} {g.get('invoice_payment_term_id_count'):>6}  {has}")

    print()
    print("=" * 100)
    print("AMBIGUITY SCREEN — terms that look ad-hoc / test / person-named")
    print("=" * 100)
    import re
    SUSPECT = re.compile(
        r"test|dummy|sample|\bpp\b|^\s*\d+%?\s*dp\s*$|"
        r"unit\s*\d+|^[A-Z]{3,}$|^\s*\d+(\.\d+)+\s*$",
        re.IGNORECASE)
    suspects = []
    for t in terms:
        nm = str(t.get("name") or "")
        if SUSPECT.search(nm):
            suspects.append(t)
    print(f"  suspect terms: {len(suspects)}/{len(terms)}")
    for t in suspects:
        tid = t["id"]
        used = next((g.get("invoice_payment_term_id_count")
                     for g in groups if (g.get("invoice_payment_term_id") or [None])[0] == tid), 0)
        print(f"    id={tid:<5} {str(t.get('name'))[:48]:<50} used on {used:>5} invoice(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())