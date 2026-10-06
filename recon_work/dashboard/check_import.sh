#!/bin/sh
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "=== import chain ==="
echo "--- addon __init__.py ---"
cat "$A/__init__.py"
echo "--- models/__init__.py ---"
cat "$A/models/__init__.py"
echo "--- models/core/__init__.py (grep installment) ---"
grep -n "installment" "$A/models/core/__init__.py"

echo ""
echo "=== is the ROOT file reachable from any import? ==="
if grep -rqs "import sale_contract_installment" "$A/__init__.py" "$A/models/__init__.py" "$A/models/core/__init__.py"; then
  echo "  REACHABLE - would double-define the model"
else
  echo "  NOT REACHABLE -> dead code (currently inert)"
fi

echo ""
echo "=== which definition wins at runtime (the real one)? ==="
docker exec -i sgc_rent_mt odoo shell -d sgc_mt_parkgroup --no-http <<'PY' 2>/dev/null | grep -e RUNTIME -e FIELDS
m = env['sale.contract.installment']
import inspect
src = inspect.getsourcefile(m.__class__)
print('RUNTIME class file : %s' % src)
f = env['ir.model.fields'].sudo().search_count([('model', '=', 'sale.contract.installment')])
print('RUNTIME db field count : %s' % f)
sel = m._fields['state'].selection
print('FIELDS state selection : %s' % (sel,))
print('FIELDS invoice_id present : %s' % ('invoice_id' in m._fields))
print('FIELDS audit mixin  : %s' % any('audit' in b for b in m.__class__.__mro__[1].__name__.lower() for b in [m.__class__.__mro__[1].__name__]))
env.cr.rollback()
PY