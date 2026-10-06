#!/bin/sh
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "=== DEFINITIVE: does the addon root __init__ import the root stray file? ==="
cat "$A/__init__.py" | grep -n "sale_contract_installment" && echo "  ^ REACHABLE" || echo "  NOT imported at addon root -> root stray file is DEAD CODE"

echo ""
echo "=== runtime truth: which state vocabulary is live? ==="
echo "  root stray file has 4 states: pending/paid/overdue (+ ?)"
echo "  live DB has 6 states (see previous run) -> models/core version is active"
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -At -c \
  "SELECT count(*) FROM ir_model_fields WHERE model='sale.contract.installment';" | sed 's/^/  live field count: /'
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -At -c \
  "SELECT count(*) FROM ir_model_fields WHERE model='sale.contract.installment' AND name='invoice_id';" | sed 's/^/  invoice_id field exists: /'