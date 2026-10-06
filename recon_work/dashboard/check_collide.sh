#!/bin/bash
# Runs on HOST. Cross-app CSS collision + Odoo theme attribute interference checks.

echo "=========== 1. who else declares sgc-kpi / sgc-panel / sgc-header etc.? ==========="
grep -rln 'sgc-kpi\|sgc-panel\|sgc-header\|sgc-watchlist\|sgc-re-dashboard' \
  /opt/odoo/deploy/sgc-rent-mt/addons --include=*.css --include=*.scss 2>/dev/null | head -20

echo ""
echo "=========== 2. per-class collisions (class defined in >1 file) ==========="
for cls in sgc-kpi sgc-panel sgc-header sgc-table sgc-chart sgc-link-btn sgc-icon-btn sgc-watchlist sgc-section sgc-two-col; do
  n=$(grep -rl "\.$cls" /opt/odoo/deploy/sgc-rent-mt/addons --include=*.css 2>/dev/null | wc -l)
  files=$(grep -rl "\.$cls" /opt/odoo/deploy/sgc-rent-mt/addons --include=*.css 2>/dev/null | sed 's|.*/addons/||' | tr '\n' ' ')
  echo "  $cls -> $n file(s): $files"
done

echo ""
echo "=========== 3. does Odoo 19 manage data-theme on <html>? ==========="
docker exec sgc_rent_mt bash -c "grep -rn 'data-theme' /usr/lib/python3/dist-packages/odoo/addons/web/static/src --include=*.js --include=*.xml 2>/dev/null | head -12"

echo ""
echo "=========== 4. who sets/removes data-theme anywhere ==========="
docker exec sgc_rent_mt bash -c "grep -rn \"setAttribute(['\\\"]data-theme\\|data-theme\" /usr/lib/python3/dist-packages/odoo/addons --include=*.js 2>/dev/null | grep -v test | head -12"

echo ""
echo "=========== 5. our dashboard css: how many rules, :has count ==========="
CSS=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management/static/src/components/rental_property_dashboard.css
echo "  :has( occurrences : $(grep -c ':has(' $CSS)"
echo "  [data-theme rules : $(grep -c 'data-theme' $CSS)"
echo "  total rules (approx): $(grep -c '{' $CSS)"