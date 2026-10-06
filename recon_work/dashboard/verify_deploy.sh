#!/bin/sh
B=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "=== deployed property_details.py project_map block ==="
grep -n -A 8 'project_map\[pr.code\]' "$B/models/core/property_details.py"

echo ""
echo "=== deployed JS escrow drill-downs ==="
grep -n 'viewUnderAllocated\|viewOverAllocated\|viewReconciled' \
  "$B/static/src/components/rental_property_dashboard.js"

echo ""
echo "=== deployed JS map popup ==="
grep -n 'bindPopup' "$B/static/src/components/rental_property_dashboard.js"

echo ""
echo "=== deployed manifest version ==="
grep -m1 '"version"' "$B/__manifest__.py"

echo ""
echo "=== deployed file sizes ==="
for f in static/src/components/rental_property_dashboard.js \
         static/src/components/rental_property_dashboard.css \
         static/src/xml/template.xml \
         models/core/property_details.py; do
  printf '  %-56s %s bytes\n' "$f" "$(wc -c < "$B/$f")"
done