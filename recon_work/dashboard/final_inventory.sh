#!/bin/sh
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "=== stray test/helper scripts inside the ADDON dir (must be none) ==="
find "$A" -maxdepth 1 -name '*.py' | while read f; do
  b=$(basename "$f")
  case "$b" in
    __init__.py|__manifest__.py) ;;
    *) echo "  STRAY: $b" ;;
  esac
done
echo "  (only __init__.py and __manifest__.py should be listed above as expected)"

echo ""
echo "=== deploy-root helper scripts (outside addon, harmless) ==="
ls /opt/odoo/deploy/sgc-rent-mt/*.py 2>/dev/null | head -20

echo ""
echo "=== addon __pycache__ cleaned? ==="
find "$A" -name '__pycache__' -type d | head -5
echo "  (empty = clean)"

echo ""
echo "=== final deployed file inventory (dashboard scope) ==="
for f in static/src/components/rental_property_dashboard.js \
         static/src/components/rental_property_dashboard.css \
         static/src/xml/template.xml \
         models/core/property_details.py \
         views/core/sale_contract_views.xml \
         views/core/property_project_views.xml \
         __manifest__.py; do
  printf '  %-56s %8s bytes\n' "$f" "$(wc -c < "$A/$f")"
done

echo ""
echo "=== manifest assets + version ==="
grep -m1 '"version"' "$A/__manifest__.py"
grep -c 'rental_property_dashboard\|components/\*\*' "$A/__manifest__.py"

echo ""
echo "=== py_compile all changed python ==="
python3 -m py_compile "$A/models/core/property_details.py" && echo "  property_details.py OK"