#!/bin/bash
# Runs INSIDE the sgc_rent_mt container (odoo source lives there).
W=/usr/lib/python3/dist-packages/odoo

echo "=========== 1. orm_service.js _read_group contract ==========="
F=$(find "$W/addons/web" -name 'orm_service.js' 2>/dev/null | head -1)
echo "file: $F"
grep -n -A 22 'async _read_group' "$F" | head -40

echo ""
echo "=========== 2. Odoo's own consumer of _read_group (how rows are indexed) ==========="
G=$(grep -rln '_read_group(' "$W/addons/web/static/src" --include=*.js 2>/dev/null | grep -v orm_service | head -1)
echo "consumer: $G"
grep -n -A 8 '_read_group(' "$G" 2>/dev/null | head -40

echo ""
echo "=========== 3. does env.company exist in the web client? ==========="
grep -rn 'env\.company' "$W/addons/web/static/src" --include=*.js 2>/dev/null | head -8
echo "--- company service registration ---"
grep -rn '"company"' "$W/addons/web/static/src/webclient" --include=*.js 2>/dev/null | head -6
grep -rn 'name: "company"' "$W/addons" --include=*.js 2>/dev/null | head -4

echo ""
echo "=========== 4. companyService payload shape (currency) ==========="
CS=$(find "$W/addons" -name 'company_service.js' 2>/dev/null | head -1)
echo "file: $CS"
grep -n -E 'currency|currentCompany|this\.env|env\.' "$CS" 2>/dev/null | head -20