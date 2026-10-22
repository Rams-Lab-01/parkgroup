import csv, os, re, json
from collections import defaultdict

def sname(s):
    """'GJ Properties Investments L.L.C (210)' -> 'GJ Properties Investments L.L.C'"""
    m = re.match(r"^(.*?)\s*\(\d+\)$", s or "")
    return m.group(1) if m else s

# --- load the old-system payment export ---
rows = []
with open("odoo_mcp/migration_out/payments.csv", newline="", encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        try:
            amt = round(float(r["amount"]), 2)
        except (ValueError, TypeError):
            continue
        rows.append(r)

by_pda = defaultdict(list)      # (partner, date, amount) -> rows
by_pa  = defaultdict(list)      # (partner, amount) -> rows
for r in rows:
    p = sname(r["partner_id"])
    a = round(float(r["amount"]), 2)
    d = r["date"]
    by_pda[(p, d, a)].append(r)
    by_pa[(p, a)].append(r)
print("old payments:", len(rows))

# --- load the 124 blanked target payments ---
blk = []
with open(os.environ["TEMP"] + r"\opencode\blank124.csv", newline="", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        blk.append(dict(pid=r["id"], ref=r["payment_ref"], partner=r["partner"],
                        date=r["paid_on"], amount=round(float(r["amount"]), 2),
                        ptype=r["payment_type"], old_unit=r["old_unit"], journal=r["journal"]))
print("target blanked:", len(blk))

# --- match ---
hit1, hit2 = [], []
for b in blk:
    k = (b["partner"], b["date"], b["amount"])
    m = by_pda.get(k, [])
    if m:
        hit1.append((b, m))
        continue
    m = by_pa.get((b["partner"], b["amount"]), [])
    if m:
        hit2.append((b, m))

print(f"exact (partner,date,amount) matched : {len(hit1)}")
print(f"loose  (partner,amount)  candidates: {len(hit2)}  (of which multi: {sum(1 for _, m in hit2 if len(m) > 1)})")
nomatch = len(blk) - len(hit1) - len(hit2)
print(f"no candidate at all : {nomatch}")

out = {"exact": [{"pid": b["pid"], "ref": b["ref"], "old_id": m["old_id"], "old_name": m["name"],
                  "old_property": m["property_id"], "old_reservation": m["reservation_id"],
                  "old_memo": m["memo"], "old_payref": m["payment_reference"], "old_journal": m["journal_id"],
                  "old_reconciled": m["reconciled_invoices_type"], "old_move": m["move_id"],
                  "old_user": m["sales_user_id"], "old_team": m["sales_team_id"],
                  "old_rec_title": m["payment_receipt_title"], "old_state": m["state"]}
                 | {k: v for k, v in b.items()} for b, m in [(b, ms[0]) for b, ms in hit1]],
       "loose": [{"pid": b["pid"], "ref": b["ref"],
                  "cands": [{"old_id": m["old_id"], "old_name": m["name"], "old_date": m["date"],
                             "old_property": m["property_id"], "old_reservation": m["reservation_id"],
                             "old_memo": m["memo"]} for m in ms[:4]]}
                 | {k: v for k, v in b.items()} for b, ms in hit2]}
os.makedirs("odoo_mcp/blank124_linkage", exist_ok=True)
with open("odoo_mcp/blank124_linkage/linkage.json", "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=1)

from collections import Counter
props = Counter(x["old_property"] for x in out["exact"])
reserv = Counter(x["old_reservation"] for x in out["exact"])
print("exact rows with old property_id set:", sum(1 for v in props if v != "False"), "| with reservation_id:", sum(1 for v in reserv if v != "False"))
print("top old_property values on exact:", [p for p in props.most_common(8)])
