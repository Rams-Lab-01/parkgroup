#!/bin/bash
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "=== manifest references vs actual file locations ==="
for name in rent_contract_report_template.xml sales_purchase_agreement_template.xml sale_contract_views.xml; do
  echo ""
  echo "--- $name ---"
  echo "  manifest mentions:"
  grep -n "$name" "$A/__manifest__.py" | sed 's/^/    /' || echo "    (none)"
  echo "  actual files in the LIVE tree (excluding backups):"
  find "$A" -name "$name" -not -path '*__pycache__*' -not -path '*/.bak-*' -not -path '*\.bak-*' 2>/dev/null | sed "s|$A/|    |"
done

echo ""
echo "=== does report/ contain them? ==="
ls "$A/report/" | grep -E 'rent_contract|sales_purchase' || echo "  NOT in report/"

echo ""
echo "=== every declared data/asset path that does NOT exist on disk (would break install) ==="
grep -oE '"[a-z_/]+\.(xml|js|css|scss|png)"' "$A/__manifest__.py" | tr -d '"' | sort -u | while read p; do
  case "$p" in
    *'*'*) continue;;
  esac
  [ -f "$A/$p" ] || echo "  MISSING: $p"
done
echo "  (no MISSING lines = manifest is complete on disk)"