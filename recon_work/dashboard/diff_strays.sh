#!/bin/sh
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "--- sizes ---"
wc -c "$A/sale_contract_installment.py" "$A/models/core/sale_contract_installment.py"

echo ""
echo "--- do the two model files declare the same model? ---"
grep -m1 "_name" "$A/sale_contract_installment.py"
grep -m1 "_name" "$A/models/core/sale_contract_installment.py"

echo ""
echo "--- field counts ---"
echo "  root : $(grep -c 'fields\.' "$A/sale_contract_installment.py")"
echo "  core : $(grep -c 'fields\.' "$A/models/core/sale_contract_installment.py")"

echo ""
echo "--- unified diff (root vs models/core) ---"
diff -u "$A/sale_contract_installment.py" "$A/models/core/sale_contract_installment.py" | head -60
echo "  (diff exit: $?)"

echo ""
echo "--- is either referenced anywhere? ---"
grep -rn "sale_contract_installment" "$A/__init__.py" "$A/models/__init__.py" 2>/dev/null
echo "  (above = the only import chain that matters)"