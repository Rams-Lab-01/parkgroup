#!/bin/bash
DB=sgc_mt_parkgroup
docker exec -i sgc_rent_mt odoo shell -d $DB --no-http <<'PYEOF' 2>&1 | grep -E '^(STEP|OK|FAIL|CARDS|FIRST|READGROUP|MENU|VISIBLE)' 
import traceback

print("STEP shell env uid:", env.uid)

# ---- STEP 1: the main payload as ADMIN (uid 2), not superuser (uid 1) ----
try:
    res = env["property.details"].with_user(2).get_development_kpis()
    keys = sorted(res.keys())
    cards_keys = ["total_units","sold_units","balance_due","required_escrow","allocated_escrow",
                  "recon_rate","missing_source_count"]
    print("OK payload as uid=2, keys:", len(keys))
    print("CARDS", {k: res.get(k) for k in cards_keys})
    print("FIRST per_project entry:", list((res.get("per_project") or {}).items())[:1])
    print("FIRST watchlist_counts:", res.get("watchlist_counts"))
except Exception as e:
    print("FAIL payload as uid=2:", type(e).__name__, e)
    traceback.print_exc()

# ---- STEP 2: the three _read_group calls the JS makes, as admin ----
try:
    c = env["sale.contract.installment"].with_user(2)._read_group(
        [("state","=","paid"),("payment_date","!=",False)], ["payment_date:month"], ["amount:sum"])
    print("READGROUP installments ok:", len(c), "groups; sum=", sum(r["amount:sum"] or 0 for r in c))
except Exception as e:
    print("FAIL readgroup installments:", type(e).__name__, e)
try:
    e2 = env["escrow.allocation"].with_user(2)._read_group([], ["project_id"], ["required_amount:sum","allocated_amount:sum"])
    print("READGROUP escrow ok:", len(e2))
except Exception as e:
    print("FAIL readgroup escrow:", type(e).__name__, e)
try:
    p = env["property.project"].with_user(2)._read_group([], ["id","name"], ["__count"])
    print("READGROUP projects ok:", len(p), [r["name"] for r in p])
except Exception as e:
    print("FAIL readgroup projects:", type(e).__name__, e)

# ---- STEP 3: drill-down domains as admin (what the card clicks open) ----
for name, model, dom in [
    ("viewOutstanding", "sale.contract", [("balance_due",">",0.01)]),
    ("viewAgedOverdue", "sale.contract", [("balance_due",">",0.01),("last_activity_date","<=","2026-07-08")]),
    ("viewUnderAllocated","escrow.allocation",[("variance_amount","<",-0.01)]),
    ("viewAwaitingSource","escrow.allocation",[("has_source_data","=",False)]),
    ("viewWithSource","escrow.allocation",[("has_source_data","=",True)]),
    ("viewAllAllocations","escrow.allocation",[]),
    ("viewAllProperties","property.details.unit",[]) if "property.details.unit" in env else ("viewAllProperties","x",[]),
]:
    if model == "x":
        continue
    try:
        n = env[model].with_user(2).search_count(dom)
        print("OK domain", name, "->", n)
    except Exception as ex:
        print("FAIL domain", name, type(ex).__name__, ex)

# ---- STEP 4: menu visibility chain for our dashboard menu ----
env.cr.execute("""
    SELECT m.id, m.name->>'en_US', m.parent_id, m.active,
           (SELECT string_agg(g.name->>'en_US', ',') FROM ir_ui_menu g
            WHERE m.groups_id IS NOT NULL AND g.id = ANY(m.groups_id))
    FROM ir_ui_menu m WHERE m.id IN (628, 631)
""")
for r in env.cr.fetchall():
    print("MENU", r)
env.cr.execute("SELECT groups_id FROM ir_ui_menu WHERE id = 631")
print("VISIBLE groups of 631:", env.cr.fetchall())
PYEOF