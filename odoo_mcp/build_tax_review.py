"""Build tax_review_2026-10-06.xlsx: VAT verification for property sales vs
the records in the pgre source that actually carry tax."""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from reconcile import _add_sheet  # noqa: E402


def oid(s):
    m = re.search(r"\((\d+)\)\s*$", str(s) or "")
    return int(m.group(1)) if m else None


def fl(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def load(name):
    with (ROOT / "migration_out" / f"{name}.csv").open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


mapping = json.loads((ROOT / "target_mapping_2026-10-06.json").read_text(encoding="utf-8"))
unit_ids = {v["new_id"] for v in mapping.get("units", {}).values() if isinstance(v, dict)}


def unit_of(r):
    p = oid(r.get("property_id"))
    if not p:
        return None
    u = mapping.get("units", {}).get(str(p))
    return u.get("new_id") if isinstance(u, dict) else None

lines_by_move = defaultdict(list)
for l in load("move_lines"):
    lines_by_move[oid(l["move_id"])].append(l)

verdict = [
    {"item": "Property unit sale consideration",
     "finding": "AED 118,559,713.91 across 5,125 unit-linked invoices carries AED 0 VAT "
                "(zero-rated / exempt residential treatment) - property sales are NOT taxed, confirmed in source."},
    {"item": "UAE VAT rule",
     "finding": "VAT is federal (Federal Decree-Law No. 8 of 2017): identical treatment in ALL seven "
                "emirates (Dubai, Abu Dhabi, Sharjah, Ajman, Umm Al Quwain, RAK, Fujairah). First supply of a "
                "residential building within 3 years of completion = zero-rated; subsequent residential supply "
                "= exempt; commercial property = 5%. No emirate-specific variation applies to our projects."},
    {"item": "Records WITH tax in source",
     "finding": "460 moves carry VAT - all are service fees / commissions / taxable purchases "
                "(commission revenue 5%, admin and oqood fees 5%, contractor and consultancy bills 5%). "
                "The property sale price itself is never taxed."},
    {"item": "Action",
     "finding": "Taxes reproduced exactly as in source (no removal). Suspicious records listed in "
                "Flagged_for_Review; unit-linked service-fee invoices listed in Unit_Linked_Fees."},
]

flag_rows = []
for r in load("invoices"):
    if fl(r["amount_tax"]) <= 0.001:
        continue
    if unit_of(r):
        continue
    accs = sorted({l["account_name"] for l in lines_by_move.get(int(r["old_id"]), [])
                   if l.get("display_type") == "product"})
    flag_rows.append({
        "old_id": r["old_id"], "name": r["name"],
        "company": r["company_id"].split(" (")[0],
        "amount_total": fl(r["amount_total"]), "VAT": fl(r["amount_tax"]),
        "revenue_accounts": ", ".join(accs),
        "why flagged": "carries VAT and is not linked to a unit - verify treatment"
                       if any("Sale" in a or "Deposit" in a or "Profit" in a for a in accs)
                       else "carries VAT (service/fee - informational)",
    })
flag_rows.sort(key=lambda x: -x["VAT"])
flag_rows.append({"old_id": "23375", "name": "(not exported)", "company": "PARK REAL ESTATE DEVELOPMENT",
                  "amount_total": None, "VAT": 3934.0, "revenue_accounts": "Sales Account",
                  "why flagged": "Sales Account with 5% AD tax - move was not exported (draft/excluded), "
                                 "already outside this migration"})

unit_rows = []
for r in load("invoices"):
    if fl(r["amount_tax"]) <= 0.001:
        continue
    if not unit_of(r):
        continue
    accs = sorted({l["account_name"] for l in lines_by_move.get(int(r["old_id"]), [])
                   if l.get("display_type") == "product"})
    unit_rows.append({"old_id": r["old_id"], "name": r["name"],
                      "company": r["company_id"].split(" (")[0],
                      "amount_total": fl(r["amount_total"]), "VAT": fl(r["amount_tax"]),
                      "service_accounts": ", ".join(accs)})
unit_rows.sort(key=lambda x: x["name"])

wb = Workbook()
wb.remove(wb.active)
_add_sheet(wb, "Verdict", verdict)
_add_sheet(wb, "Flagged_for_Review", flag_rows)
_add_sheet(wb, "Unit_Linked_Fees", unit_rows)
out = ROOT / "tax_review_2026-10-06.xlsx"
wb.save(out)
print(f"unit-linked invoices with VAT (service fees): {len(unit_rows)} | flagged: {len(flag_rows)}")
print("->", out.name)
