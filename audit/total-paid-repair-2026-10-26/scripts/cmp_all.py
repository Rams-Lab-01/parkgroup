"""Read-only: every prod unit vs PGRE (price, and paid on the live deal). Writes cmp_all.csv."""
import csv
from collections import defaultdict
from pgre_env import c

BLD = {"PARK BEACH RESIDENCE": "Park Beach Residence I", "PARK BEACH RESIDENCE II": "Park Beach Residence II",
       "Park Residency": "Park Residency", "Park Golf View Residence": "Park Golf Views"}
ANY = ["|", ("active", "=", True), ("active", "=", False)]
pg = {}
for u in c.iter_search_read("product.template", ANY + [("is_property", "=", True)],
                            ["name", "project_worksite_id", "net_price", "price_before_discount", "discount", "state"]):
    b = BLD.get((u["project_worksite_id"] or [0, ""])[1])
    if b:
        pg[(b, u["name"].strip().upper())] = u
leads = defaultdict(list)
for l in c.iter_search_read("crm.lead", ANY + [("property_id", "in", [u["id"] for u in pg.values()])],
                            ["property_id", "partner_id", "stage_id", "active", "paid", "amount_total", "expected_revenue"]):
    leads[l["property_id"][0]].append(l)

out, n = [], 0
for r in csv.DictReader(open("prod_units.csv", encoding="utf-8")):
    b, _, rest = r["name"].partition(" - ")
    key = (b, rest.split()[-1].upper() if rest else r["name"].upper())
    u = pg.get(key)
    n += 1
    price = float(r["sale_price"] or 0)
    if not u:
        out.append([r["name"], r["state"], price, "", "", "NOT IN PGRE", r["contract"], r["total_paid"], "", ""])
        continue
    live = [l for l in leads[u["id"]] if l["active"] and (l["stage_id"] or [0, ""])[1] not in ("New", "Lost")]
    lp = max(live, key=lambda l: l["paid"]) if live else None
    diff = round(price - u["net_price"], 2)
    paid_pg = lp["paid"] if lp else ""
    flag = []
    if abs(diff) > 1: flag.append("PRICE")
    if r["state"] in ("sold", "booked") and u["state"] == "free": flag.append("SOLD-ONLY-IN-PROD")
    if r["total_paid"] and lp and abs(float(r["total_paid"]) - lp["paid"]) > 1: flag.append("PAID")
    out.append([r["name"], r["state"], price, u["state"], u["net_price"], " ".join(flag) or "ok", r["contract"],
                r["total_paid"], paid_pg, (lp["partner_id"] or [0, ""])[1] if lp else ""])
with open("cmp_all.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["prod_unit", "prod_state", "prod_price", "pgre_state", "pgre_net_price", "flags", "prod_contract",
                "prod_total_paid", "pgre_paid_live_deal", "pgre_buyer"])
    w.writerows(out)
from collections import Counter
cnt = Counter()
for x in out:
    for f in (x[5].split(" ") if x[5] not in ("ok",) else ["ok"]):
        cnt[f] += 1
print(n, "prod units |", dict(cnt))
for x in out:
    if "PRICE" in x[5] or "NOT" in x[5] or "SOLD-ONLY" in x[5]:
        print(f"  {x[0][:45]:45} | prod {x[1]:9} {x[2]:>14,.2f} | PGRE {x[3]:9} {x[4] if x[4]=='' else format(x[4], ',.2f'):>14} | {x[5]}")
