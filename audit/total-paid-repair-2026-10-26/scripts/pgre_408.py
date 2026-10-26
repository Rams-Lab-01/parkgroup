"""Read-only: PGRE money for PBR 408 (Goldsmith) + where Park Residency lives in PGRE."""
from pgre_env import c
ANY = ["|", ("active", "=", True), ("active", "=", False)]
print("companies:", [(x["id"], x["name"]) for x in c.search_read("res.company", [], ["name"])])
p = c.search_read("res.partner", ANY + [("name", "ilike", "Goldsmith")], ["name"])
pids = [x["id"] for x in p]
print("partners:", p)
pays = c.search_read("account.payment", [("partner_id", "in", pids)],
                     ["name", "date", "amount", "payment_type", "state", "memo", "journal_id", "is_reconciled"],
                     order="date")
tot = 0
for x in pays:
    if x["payment_type"] == "inbound" and x["state"] not in ("draft", "canceled", "cancel", "rejected"):
        tot += x["amount"]
    print(f"  PAY {x['name']} {x['date']} {x['payment_type']} {x['state']} {x['amount']:,.2f} rec={x['is_reconciled']} "
          f"| {(x['journal_id'] or [0,''])[1]} | {x['memo']}")
print(f"  inbound non-draft total {tot:,.2f}  ({len(pays)} payments)")
inv = c.search_read("account.move", [("partner_id", "in", pids), ("move_type", "in", ["out_invoice", "out_refund"]),
                                     ("state", "=", "posted")],
                    ["name", "invoice_date", "amount_total", "amount_residual", "payment_state", "ref"], order="invoice_date")
print(f"  posted invoices {len(inv)} | total {sum(i['amount_total'] for i in inv):,.2f} | "
      f"residual {sum(i['amount_residual'] for i in inv):,.2f} | settled {sum(i['amount_total']-i['amount_residual'] for i in inv):,.2f}")

print("\n=== Park Residency in PGRE ===")
for q in ["Belousov", "Tahmina"]:
    for l in c.search_read("crm.lead", ANY + [("partner_id.name", "ilike", q)],
                           ["name", "partner_id", "stage_id", "property_id", "company_id", "amount_total", "paid", "create_date"]):
        print(f"  LEAD[{q}] {l['id']} {l['name']!r} | {(l['partner_id'] or [0,''])[1]} | {(l['stage_id'] or [0,''])[1]} "
              f"| unit {(l['property_id'] or [0,''])[1]} | co {(l['company_id'] or [0,''])[1]} | total {l['amount_total']:,.2f} paid {l['paid']:,.2f}")
    for x in c.search_read("res.partner", ANY + [("name", "ilike", q)], ["name", "company_id"]):
        print(f"  PARTNER[{q}] {x}")
print("  leads named like Residency:", c.search_count("crm.lead", ANY + [("name", "ilike", "Residency")]))
print("  units named like Residency:", c.search_count("product.template", ANY + [("name", "ilike", "Residency")]))
