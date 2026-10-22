import json, sys, io
from collections import defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
rows = json.load(open("odoo_mcp/blank124_linkage/final_rows.json", encoding="utf-8"))
print("=== Fatlawi 12 detail (tgt unit numbers) ===")
for r in rows:
    if "Fatlawi" in r["partner"]:
        print(r["pid"], r["ref"], r["date"], r["amount"], "old-tgt:", r["tgt_project"], r["tgt_unit_no"], "| res:", r["resolve"])

bad = [r for r in rows if r["resolve"] and r["resolve"].startswith("exact") and r["agree_with_old"] is False]
print("\nrows where pgre unit number != target pre-blank unit number:", len(bad))
for r in bad[:10]:
    print("  ", r["pid"], r["tgt_unit_no"], "->", r["unit_final"])

import csv as _csv
w = _csv.writer(open("odoo_mcp/blank124_linkage/vendor_plan.csv", "w", newline="", encoding="utf-8"))
v = defaultdict(lambda: {"n": 0, "res": 0, "units": set(), "srcs": set()})
for r in rows:
    d = v[r["partner"]]
    d["n"] += 1
    if r["unit_final"]:
        d["res"] += 1
        d["units"].add("%s / unit %s" % (r["pgre_community"] or "?", r["unit_final"]))
        d["srcs"].add(r["resolve"])
        w.writerow([r["pid"], r["partner"], r["amount"], r["date"], r["unit_final"], r["pgre_community"], r["resolve"]])
print()
for k, dd in v.items():
    print(k[:55], "n=%s resolved=%s" % (dd["n"], dd["res"]), "|", sorted(dd["units"]), "|", sorted(dd["srcs"]))
