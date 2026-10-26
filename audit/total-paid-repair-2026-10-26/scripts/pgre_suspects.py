"""Read-only: PGRE view of the units whose prod Total Paid looks overstated."""
from pgre_env import c
ANY = ["|", ("active", "=", True), ("active", "=", False)]
W = {"I": "PARK BEACH RESIDENCE", "II": "PARK BEACH RESIDENCE II", "PRY": "Park Residency"}
SUS = [("II", "712"), ("I", "202"), ("II", "203"), ("II", "309"), ("II", "410"), ("I", "208"), ("II", "614"),
       ("II", "204"), ("II", "505"), ("II", "107"), ("I", "105"), ("PRY", "408"), ("I", "708")]
NOK = {"draft", "canceled", "cancel", "rejected"}
for b, no in SUS:
    u = c.search_read("product.template", ANY + [("name", "=", no), ("project_worksite_id.name", "=", W[b])], ["net_price", "state"])
    if not u: print(b, no, "NOT FOUND"); continue
    u = u[0]
    leads = c.search_read("crm.lead", ANY + [("property_id", "=", u["id"])],
                          ["partner_id", "stage_id", "active", "paid", "amount_total"])
    print(f"PBR {b} {no}" if b != "PRY" else f"PRY {no}", f"| PGRE price {u['net_price']:,.2f} {u['state']}")
    for l in leads:
        pid = (l["partner_id"] or [0, ""])[0]
        pays = c.search_read("account.payment", [("partner_id", "=", pid), ("payment_type", "=", "inbound")],
                             ["amount", "state", "is_reconciled"]) if pid else []
        rec = sum(p["amount"] for p in pays if p["state"] not in NOK)
        unrec = sum(p["amount"] for p in pays if p["state"] not in NOK and not p["is_reconciled"])
        print(f"    lead {l['id']:4} {(l['partner_id'] or [0,''])[1][:38]:38} | {(l['stage_id'] or [0,''])[1]:11} active={l['active']!s:5} "
              f"| deal {l['amount_total']:>13,.2f} | paid {l['paid']:>13,.2f} | partner receipts {rec:>13,.2f} ({len(pays)}) unapplied {unrec:,.2f}")
