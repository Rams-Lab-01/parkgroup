#!/bin/bash
echo "=========== 1. orm_service.js _read_group (frontend contract) ==========="
find /usr/lib/python3/dist-packages/odoo/addons/web -name 'orm_service.js' | head -2
F=$(find /usr/lib/python3/dist-packages/odoo/addons/web -name 'orm_service.js' | head -1)
grep -n -A 30 '_read_group' "$F" | head -60

echo ""
echo "=========== 2. Python _read_group return shape (row type) ==========="
grep -rn 'def _read_group' /usr/lib/python3/dist-packages/odoo/models.py | head -3
grep -n -A 12 'def _read_group(' /usr/lib/python3/dist-packages/odoo/models.py | head -40
echo "  --- return statement / named result ---"
grep -n 'namedtuple\|_read_group_result\|return result\|return list' /usr/lib/python3/dist-packages/odoo/models.py | sed -n '1,20p'

echo ""
echo "=========== 3. does the web client env have .company ? ==========="
grep -rn 'env\.company\b' /usr/lib/python3/dist-packages/odoo/addons/web/static/src --include=*.js | head -10
echo "  --- company service / provide ---"
grep -rn 'company:' /usr/lib/python3/dist-packages/odoo/addons/web/static/src/webclient/webclient.js | head -5
grep -rn 'this.env = \|env: {' /usr/lib/python3/dist-packages/odoo/addons/web/static/src/webclient/webclient.js | head -10

echo ""
echo "=========== 4. Python-side actual JSON wire format ==========="
docker exec -i sgc_rent_mt odoo shell -d sgc_mt_parkgroup --no-http <<'PYEOF' 2>&1 | grep -E '^(WIRE|ROWTYPE|G1|G2)'
import json, datetime
rows = env["sale.contract.installment"]._read_group(
    [("state","=","paid"),("payment_date","!=",False)], ["payment_date:month"], ["amount:sum"])
print("ROWTYPE:", type(rows), "len:", len(rows))
print("ROW0 type:", type(rows[0]) if rows else None)
try:
    print("ROW0:", rows[0])
except Exception as e:
    print("ROW0 err", e)
try:
    print("WIRE:", json.dumps(rows[:2], default=str)[:400])
except Exception as e:
    print("WIRE err:", e)
# dicts or tuples?
if rows:
    r = rows[0]
    print("G1 dict-like keys:", list(r.keys()) if hasattr(r, "keys") else "NO KEYS ->", type(r))
    try:
        v = r["amount:sum"]; print("G2 index by str OK:", v)
    except Exception as e:
        print("G2 str-index FAILED:", type(e).__name__, e)
    try:
        print("G2b by int index:", r[0], "|", r[1])
    except Exception as e:
        print("G2b int-index failed:", e)
PYEOF