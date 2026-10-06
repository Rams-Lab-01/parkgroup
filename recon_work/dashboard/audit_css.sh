#!/bin/bash
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management
CSS="$A/static/src/components/rental_property_dashboard.css"
OLD="$A/static/src/css/style.css"

echo "=== menus that use a CLIENT action, with the tag ==="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -c "
SELECT m.id, m.name->>'en_US' AS menu, m.action, a.id AS act_id, a.tag
FROM ir_ui_menu m
LEFT JOIN ir_act_client a ON m.action = 'ir.actions.client,' || a.id
WHERE m.action LIKE 'ir.actions.client%'
ORDER BY m.id;" 2>&1 | head -20

echo ""
echo "=== our menu (631) and action 900 ==="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -c "
SELECT m.id AS menu_id, m.name->>'en_US' AS menu, m.parent_id, m.action, a.tag
FROM ir_ui_menu m LEFT JOIN ir_act_client a ON a.id = 900
WHERE m.id = 631;" 2>&1 | head -8

echo ""
echo "=== theme implementation in dashboard CSS ==="
echo "  [data-theme] selectors : $(grep -c 'data-theme' "$CSS")"
echo "  CSS custom properties  : $(grep -cE '^\s*--[a-z-]+:' "$CSS")"
echo "  :root block            : $(grep -c ':root' "$CSS")"
echo "  hardcoded hex colours  : $(grep -oE '#[0-9a-fA-F]{3,8}' "$CSS" | wc -l)"
echo "  prefers-color-scheme   : $(grep -c 'prefers-color-scheme' "$CSS")"
echo ""
echo "  --- the variable declarations (first 30) ---"
grep -nE '^\s*--[a-z-]+:' "$CSS" | head -30
echo ""
echo "  --- any [data-theme] rules ---"
grep -n 'data-theme' "$CSS" | head -20

echo ""
echo "=== the OLD stylesheet: does it fight the new one? ==="
echo "  size: $(wc -c < "$OLD") bytes"
echo "  data-theme refs: $(grep -c 'data-theme' "$OLD")"
echo "  sgc- class refs: $(grep -oE '\.sgc-[a-z-]+' "$OLD" | sort -u | wc -l)"
echo "  hardcoded hex: $(grep -oE '#[0-9a-fA-F]{3,8}' "$OLD" | wc -l)"
echo ""
echo "  shared class names between old and new (potential conflicts):"
comm -12 <(grep -oE '\.sgc-[a-z0-9_-]+' "$OLD" | sort -u) <(grep -oE '\.sgc-[a-z0-9_-]+' "$CSS" | sort -u) | head -25

echo ""
echo "=== template: theme toggle + aria/semantic markup ==="
TPL="$A/static/src/xml/template.xml"
echo "  theme toggle button refs: $(grep -c 'toggleTheme' "$TPL")"
echo "  aria- attributes:        $(grep -c 'aria-' "$TPL")"
echo "  role= attributes:        $(grep -c 'role=' "$TPL")"
echo "  <button> elements:       $(grep -o '<button' "$TPL" | wc -l)"
echo "  <div t-on-click> (non-button interactive): $(grep -o 'div[^>]*t-on-click' "$TPL" | wc -l)"
echo "  alt attributes:          $(grep -c 'alt=' "$TPL")"