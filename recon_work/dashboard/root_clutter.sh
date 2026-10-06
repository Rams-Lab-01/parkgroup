#!/bin/bash
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "=== are root-level XMLs referenced by the manifest data list? ==="
for f in sale_contract_views.xml rent_contract_report_template.xml sales_purchase_agreement_template.xml; do
  if grep -q "\"$f\"" "$A/__manifest__.py"; then
    echo "  *** REFERENCED: $f  (would load from addon root) ***"
    grep -n "\"$f\"" "$A/__manifest__.py"
  else
    echo "  not referenced: $f  (inert)"
  fi
done

echo ""
echo "=== any data entry NOT under a subdirectory (root-level loads)? ==="
grep -oE '"[a-z_]+\.xml"' "$A/__manifest__.py" | sort -u | head -20
echo "  (empty = every declared xml lives in a subfolder)"

echo ""
echo "=== do the stray XMLs duplicate files in views/? ==="
for f in sale_contract_views.xml; do
  echo "  root $f: $(wc -c < "$A/$f") bytes, $(md5sum "$A/$f" | cut -c1-12)"
  find "$A" -name "$f" -not -path '*__pycache__*' | while read p; do
    [ "$p" = "$A/$f" ] && continue
    echo "    vs $p: $(wc -c < "$p") bytes, $(md5sum "$p" | cut -c1-12)"
  done
done

echo ""
echo "=== backup / rename artifacts at addon root ==="
ls -la "$A"/*.bak-* "$A"/*.rename-* 2>/dev/null | awk '{print "  "$5" bytes  "$9}'

echo ""
echo "=== root-level directories (inspect before touching) ==="
for d in docs ops services tools "video and ss"; do
  if [ -d "$A/$d" ]; then
    echo "  $d/: $(find "$A/$d" -type f | wc -l) files, $(du -sh "$A/$d" | cut -f1)"
    find "$A/$d" -type f | head -4 | sed 's/^/      /'
  fi
done