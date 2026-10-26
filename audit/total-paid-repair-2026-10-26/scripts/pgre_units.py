"""Read-only: PGRE (pgre.odoo.com) view of the units whose prod price/collection is in question."""
from collections import defaultdict
from pgre_env import c

WANT = [("PARK BEACH RESIDENCE II", "212"), ("PARK BEACH RESIDENCE II", "705"),
        ("PARK BEACH RESIDENCE II", "709"), ("PARK BEACH RESIDENCE", "408")]
UF = ["name", "project_worksite_id", "state", "list_price", "price_before_discount", "discount", "discount_type",
      "net_price", "fsp_incl_charges", "collected_amount"]
LF = ["name", "partner_id", "stage_id", "active", "create_date", "date_closed", "payment_plan_id",
      "amount_total", "expected_revenue", "paid", "balance", "advance_payment"]
ANY = ["|", ("active", "=", True), ("active", "=", False)]

for proj, no in WANT:
    units = c.search_read("product.template", ANY + [("name", "=", no), ("project_worksite_id.name", "=", proj)], UF)

    print(f"\n######## {proj} {no}: {len(units)} unit record(s)")
    for u in units:
        print(f"  UNIT {u['id']} {u['name']!r} | proj {(u['project_worksite_id'] or [0,''])[1]} | state {u['state']}")
        print(f"       list {u['list_price']:,.2f} | before-disc {u['price_before_discount']:,.2f} | "
              f"disc {u['discount']} ({u['discount_type']}) | net/FSP {u['net_price']:,.2f} | "
              f"FSP+charges {u['fsp_incl_charges']:,.2f} | collected {u['collected_amount']:,.2f}")
        leads = c.search_read("crm.lead", ANY + [("property_id", "=", u["id"])], LF)
        for l in sorted(leads, key=lambda x: x["create_date"]):
            print(f"    LEAD {l['id']} {l['name']!r} | {(l['partner_id'] or [0,''])[1]} | "
                  f"stage {(l['stage_id'] or [0,''])[1]} | active {l['active']} | created {l['create_date'][:10]}")
            print(f"         total {l['amount_total']:,.2f} | exp.rev {l['expected_revenue']:,.2f} | "
                  f"paid {l['paid']:,.2f} | balance {l['balance']:,.2f} | plan {(l['payment_plan_id'] or [0,''])[1]}")
            ll = c.search_read("loan.line", [("lead_id", "=", l["id"])],
                               ["name", "amount", "percentage", "payment_state", "amount_residual", "invoice_id"])
            if ll:
                s = defaultdict(float)
                for r in ll:
                    s[r["payment_state"] or "none"] += r["amount"]
                print(f"         loan.lines {len(ll)} | sum {sum(r['amount'] for r in ll):,.2f} "
                      f"({sum(r['percentage'] for r in ll):.2f}%) | residual {sum(r['amount_residual'] or 0 for r in ll):,.2f} "
                      f"| by state " + ", ".join(f"{k} {v:,.2f}" for k, v in s.items()))
