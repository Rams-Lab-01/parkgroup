#!/bin/bash
echo "=========== 1. orm_service.js _read_group (frontend contract) ==========="
F=$(find /usr/lib/python3/dist-packages/odoo/addons/web -name 'orm_service.js' 2>/dev/null | head -1)
echo "file: $F"
grep -n -B2 -A 28 '_read_group(' "$F" | head -70

echo ""
echo "=========== 2. how Odoo's own code consumes _read_group rows ==========="
grep -rn '_read_group(' /usr/lib/python3/dist-packages/odoo/addons --include=*.js 2>/dev/null | grep -v orm_service | head -6
echo "  --- sample consumer (tuple indexing?) ---"
G=$(grep -rln '_read_group(' /usr/lib/python3/dist-packages/odoo/addons/web/static/src --include=*.js | grep -v orm_service | head -1)
echo "consumer: $G"
grep -n -A6 '_read_group(' "$G" | head -30

echo ""
echo "=========== 3. does env.company exist in the web client ? ==========="
echo "--- direct env.company assignments/usages in web addon ---"
grep -rn 'env\.company' /usr/lib/python3/dist-packages/odoo/addons/web/static/src --include=*.js 2>/dev/null | head -8
echo "--- where the client env is composed ---"
grep -rn 'company:' /usr/lib/python3/dist-packages/odoo/addons/web/static/src/webclient/*.js 2>/dev/null | head -8
echo "--- company service provided? ---"
grep -rn 'name: "company"' /usr/lib/python3/dist-packages/odoo/addons/web/static/src --include=*.js 2>/dev/null | head -4

echo ""
echo "=========== 4. currency symbol via company service ==========="
grep -rn 'currency_id' /usr/lib/python3/dist-packages/odoo/addons/web/static/src/core/currency/*.js 2>/dev/null | head -6
grep -rn 'currency' /usr/lib/python3/dist-packages/odoo/addons/web/static/src/webclient/company_service.js 2>/dev/null | head -10