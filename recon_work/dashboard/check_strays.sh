#!/bin/sh
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "--- dates of the two root files ---"
ls -la "$A/sale_contract_installment.py" "$A/verify_luxury.py" 2>&1

echo ""
echo "--- addon __init__.py (what the module imports) ---"
cat "$A/__init__.py"

echo ""
echo "--- where does the REAL installment model live? ---"
find "$A" -name 'sale_contract_installment.py' -not -path '*__pycache__*'

echo ""
echo "--- head of the ROOT stray file ---"
head -14 "$A/sale_contract_installment.py"

echo ""
echo "--- head of verify_luxury.py ---"
head -10 "$A/verify_luxury.py"