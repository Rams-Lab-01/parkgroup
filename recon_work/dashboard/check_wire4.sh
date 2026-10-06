#!/bin/bash
# Runs INSIDE the sgc_rent_mt container.
W=/usr/lib/python3/dist-packages/odoo/addons

echo "=========== 1. env.company EXACT usage across all addons ==========="
grep -rn 'env\.company[^S]' "$W" --include=*.js 2>/dev/null | head -10
echo "  count: $(grep -rn 'env\.company[^S]' "$W" --include=*.js 2>/dev/null | wc -l)"

echo ""
echo "=========== 2. company service in Odoo 19 ==========="
grep -rn 'services").add("company"' "$W" --include=*.js 2>/dev/null | head -4
grep -rn 'useService("company")' "$W" --include=*.js 2>/dev/null | head -4
echo "--- files named *company* in web ---"
find "$W/web/static/src" -name '*company*' | head -10

echo ""
echo "=========== 3. _read_group in orm_service.js ==========="
grep -n -B3 -A 25 '_read_group' "$W/web/static/src/core/orm_service.js" | head -60

echo ""
echo "=========== 4. Odoo consumer example ==========="
G=$(grep -rln '_read_group(' "$W" --include=*.js 2>/dev/null | grep -v 'orm_service' | head -1)
echo "consumer: $G"
grep -n -A 10 '_read_group(' "$G" 2>/dev/null | head -35

echo ""
echo "=========== 5. how to read company name + currency in Odoo 19 frontend ==========="
grep -rn 'currency_id' "$W/web/static/src" --include=*.js 2>/dev/null | head -8
grep -rn 'currentCompany' "$W/web/static/src" --include=*.js 2>/dev/null | head -8