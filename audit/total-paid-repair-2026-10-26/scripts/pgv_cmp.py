"""Read-only: Park Golf View Residence unit prices, PGRE vs prod (prod figures pasted from the SELECT)."""
from pgre_env import c
PROD = {"101": 1242983.00, "102": 1296020.10, "103": 1339602.60, "201": 1268350.00, "202": 1316839.70,
        "203": 1363104.40, "301": 1293717.00, "302": 1348069.10, "303": 1386606.20, "401": 1319084.00,
        "402": 1374093.60, "403": 1410108.00, "G01": 4914080.00, "R01": 4500000.00, "104": 711848.80,
        "204": 732382.90, "304": 752917.00, "404": 838475.75}
ANY = ["|", ("active", "=", True), ("active", "=", False)]
us = c.search_read("product.template", ANY + [("project_worksite_id.name", "=", "Park Golf View Residence")],
                   ["name", "state", "price_before_discount", "discount", "net_price", "unit_type"])
seen = set()
for u in sorted(us, key=lambda x: x["name"]):
    no = u["name"].strip().upper()
    seen.add(no)
    leads = c.search_read("crm.lead", ANY + [("property_id", "=", u["id"])], ["name", "partner_id", "stage_id", "active", "paid"])
    lt = "; ".join(f"{(l['partner_id'] or [0,'?'])[1]}/{(l['stage_id'] or [0,''])[1]}{'' if l['active'] else '(arch)'}/paid {l['paid']:,.0f}" for l in leads)
    p = PROD.get(no)
    d = "n/a" if p is None else f"{p - u['net_price']:+,.2f}"
    print(f"{no:>4} | {u['unit_type'] or '':10} | PGRE {u['state']:9} net {u['net_price']:>13,.2f} (before {u['price_before_discount']:,.2f}, disc {u['discount']}) "
          f"| prod {p if p is None else f'{p:,.2f}'} | diff {d} | {lt}")
print("prod units not in PGRE:", sorted(set(PROD) - seen))
