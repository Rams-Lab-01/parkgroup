#!/bin/bash
set -uo pipefail

A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management
Q=/opt/odoo/deploy/sgc-rent-mt/_quarantine_20261006

echo "=== verify asset paths correctly (strip module prefix) ==="
for p in static/src/css/style.css static/src/js/rental.js static/src/lib/leaflet.js static/src/xml/template.xml; do
  if [ -f "$A/$p" ]; then echo "  present: $p"; else echo "  *** MISSING: $p ***"; fi
done

echo ""
echo "=== check the stray XML inside models/core ==="
if grep -q 'models/core/sales_purchase_agreement_template.xml' "$A/__manifest__.py"; then
  echo "  REFERENCED from models/core -> keep"
else
  echo "  not referenced -> redundant copy (live one is report/sales_purchase_agreement_template.xml)"
fi

echo ""
echo "=== quarantine 1: redundant root XMLs (live copies exist in proper dirs) ==="
mkdir -p "$Q/redundant_root"
for f in sale_contract_views.xml rent_contract_report_template.xml sales_purchase_agreement_template.xml; do
  if [ -f "$A/$f" ]; then mv "$A/$f" "$Q/redundant_root/"; echo "  moved: $f"; fi
done

echo ""
echo "=== quarantine 2: backup / rename artifacts everywhere in the addon ==="
mkdir -p "$Q/backups"
find "$A" \( -name '*.bak-*' -o -name '*.rename-*' \) -not -path '*__pycache__*' 2>/dev/null | while read f; do
  rel="${f#$A/}"
  mkdir -p "$Q/backups/$(dirname "$rel")"
  mv "$f" "$Q/backups/$rel"
  echo "  moved: $rel"
done

echo ""
echo "=== quarantine 3: the report backup directory ==="
if [ -d "$A/report.bak-20260923" ]; then
  mv "$A/report.bak-20260923" "$Q/"
  echo "  moved: report.bak-20260923/ ($(find "$Q/report.bak-20260923" -type f | wc -l) files)"
fi

echo ""
echo "=== quarantine 4: stray template inside models/core (if unreferenced) ==="
if ! grep -q 'models/core/sales_purchase_agreement_template.xml' "$A/__manifest__.py"; then
  if [ -f "$A/models/core/sales_purchase_agreement_template.xml" ]; then
    mv "$A/models/core/sales_purchase_agreement_template.xml" "$Q/redundant_root/"
    echo "  moved: models/core/sales_purchase_agreement_template.xml"
  fi
fi

echo ""
echo "=== post-cleanup addon root ==="
ls "$A" | sed 's/^/  /'

echo ""
echo "=== py_compile check ==="
python3 -m py_compile "$A/models/core/property_details.py" && echo "  OK"

echo ""
echo "=== integrity: manifest-declared files still all present? ==="
missing=0
grep -oE '"[a-z_/]+\.(xml|js|css|scss|png)"' "$A/__manifest__.py" | tr -d '"' | sort -u | while read p; do
  case "$p" in *'*'*) continue;; esac
  case "$p" in sgc_offplan_rental_property_management/*) p="${p#sgc_offplan_rental_property_management/}";; esac
  [ -f "$A/$p" ] || echo "  *** MISSING AFTER CLEANUP: $p ***"
done
echo "  (only real missing files are printed above)"

echo ""
echo "CLEANUP_PHASE2_DONE"