import csv, json, os
from collections import defaultdict
from datetime import datetime

rows = json.load(open("odoo_mcp/blank124_linkage/final_rows.json", encoding="utf-8"))
out = []
for r in rows:
    ev = json.loads(r["ev"]) if r["ev"] else {}
    out.append({
        "pid": r["pid"], "payment_ref": r["ref"], "partner": r["partner"], "date": r["date"],
        "amount": r["amount"],
        "old_unit_before_blank": "%s - unit %s" % (r["tgt_project"] or "-", r["tgt_unit_no"] or "-"),
        "proposed_unit": r["unit_final"] or "",
        "proposed_project": r["pgre_community"] or "",
        "evidence_source": r["resolve"] or "finance-needed",
        "pgre_old_payment_id": ev.get("old_payment", ""),
        "pgre_old_payment_date": ev.get("old_date", ""),
        "crm_units_in_pgre": r["crm_units"],
    })
with open("odoo_mcp/blank124_linkage/pgre_relink_124.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(out[0]))
    w.writeheader(); w.writerows(out)

tot = defaultdict(lambda: [0, 0.0, 0])
v = defaultdict(lambda: [0, 0.0, 0])
for r in rows:
    d = v[r["partner"]]
    d[0] += 1
    d[1] += r["amount"]
    if r["unit_final"]:
        d[2] += r["amount"]
print("%-58s %4s %12s %12s" % ("vendor", "n", "total", "resolvable"))
for k, (n, t, rr) in sorted(v.items(), key=lambda kv: -kv[1][1]):
    print("%-58s %4d %12s %12s" % (k[:58], n, "%.2f" % t, "%.2f" % rr))
print("%-58s %4d %12s %12s" % ("TOTAL", len(rows), "%.2f" % sum(d[1] for d in v.values()), "%.2f" % sum(d[2] for d in v.values())))

bid = datetime.now().strftime("20261022")
print("\nprofit sheet -> pgre_relink_124.csv rows:", len(out))
json.dump(out, open("odoo_mcp/blank124_linkage/pgre_relink_124.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
