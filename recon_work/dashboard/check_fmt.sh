#!/bin/bash
DB=sgc_mt_parkgroup
docker exec -i sgc_rent_mt odoo shell -d $DB --no-http <<'PYEOF' 2>&1 | grep -E '^(FMT|KEYS|ROW|PAYCUR|SESS|TOK|OK|FAIL)'
import json, traceback

# ---- 1. the REAL method the browser calls: formatted_read_group ----
try:
    rows = env["sale.contract.installment"].formatted_read_group(
        domain=[("state","=","paid"),("payment_date","!=",False)],
        groupby=["payment_date:month"],
        aggregates=["amount:sum"],
    )
    print("FMT type:", type(rows), "len:", len(rows))
    print("ROW0:", json.dumps(rows[0], default=str)[:400])
    print("KEYS:", sorted(rows[0].keys()))
    r = rows[0]
    print("OK access r['payment_date'] =", r.get("payment_date"))
    print("OK access r['amount:sum'] =", r.get("amount:sum"))
except Exception as e:
    print("FAIL formatted_read_group:", type(e).__name__, e)
    traceback.print_exc()

# ---- 2. escrow + project read_group as the browser does ----
try:
    er = env["escrow.allocation"].formatted_read_group(
        domain=[], groupby=["project_id"],
        aggregates=["required_amount:sum","allocated_amount:sum"])
    print("FMT escrow len:", len(er), "ROW0:", json.dumps(er[0], default=str)[:300])
    print("KEYS:", sorted(er[0].keys()))
except Exception as e:
    print("FAIL escrow fmt:", type(e).__name__, e)
try:
    pr = env["property.project"].formatted_read_group(
        domain=[], groupby=["id","name"], aggregates=["__count"])
    print("FMT proj len:", len(pr), "ROW0:", json.dumps(pr[0], default=str)[:300])
    print("KEYS:", sorted(pr[0].keys()))
except Exception as e:
    print("FAIL proj fmt:", type(e).__name__, e)

# ---- 3. does the payload carry currency/company already? ----
p = env["property.details"].get_development_kpis()
print("PAYCUR has currency_symbol:", "currency_symbol" in p, "| has company_name:", "company_name" in p)
print("PAYCUR sample keys:", sorted(p.keys()))

# ---- 4. can we forge a valid session without touching passwords? ----
try:
    from odoo import http
    sess = http.root.session_store.new()
    print("SESS new sid:", getattr(sess, "sid", None))
    print("SESS attrs:", [a for a in dir(sess) if not a.startswith("_")][:40])
except Exception as e:
    print("FAIL session:", type(e).__name__, e)

# find session token helper
import odoo.http as H
cands = [n for n in dir(H) if "token" in n.lower() or "session" in n.lower()]
print("TOK helpers in odoo.http:", cands)
try:
    import inspect
    from odoo.http import Session
    src = inspect.getsource(Session)
    for line in src.splitlines():
        if "session_token" in line or "def check_security" in line:
            print("TOK", line.strip())
except Exception as e:
    print("FAIL inspect:", e)
PYEOF