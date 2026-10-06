#!/bin/bash
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "=== ALL js files in the module and what they register ==="
for f in $(find "$A/static/src" -name '*.js' -not -name '*.min.js' -not -path '*__pycache__*'); do
  reg=$(grep -c 'registry.category("actions")' "$f" 2>/dev/null)
  adds=$(grep -oE '\.add\("[a-z_]+"' "$f" 2>/dev/null | sort -u | tr '\n' ' ')
  echo "  ${f#$A/}"
  echo "      registry refs=$reg  adds: $adds"
done

echo ""
echo "=== ALL template names declared in xml files ==="
for f in $(find "$A/static/src" -name '*.xml' -not -path '*__pycache__*'); do
  names=$(grep -oE 't-name="[^"]+"' "$f" 2>/dev/null | sort -u | tr '\n' ' ')
  echo "  ${f#$A/}:  $names"
done

echo ""
echo "=== which file defines the property_dashboard action tag? ==="
grep -rn 'property_dashboard' "$A/static/src" --include=*.js --include=*.xml | grep -v '\.min\.js'

echo ""
echo "=== the client action record in DB (tag + what it points at) ==="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -c \
"SELECT d.name AS xml_id, a.tag, a.name->>'en_US' AS label FROM ir_model_data d JOIN ir_act_client a ON a.id=d.res_id WHERE d.name='action_property_dashboard';" 2>&1 | head -8

echo ""
echo "=== menu -> action wiring ==="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -c \
"SELECT m.name->>'en_US' AS menu, m.action FROM ir_ui_menu m WHERE m.action LIKE '%property_dashboard%' OR m.name->>'en_US' ILIKE '%dashboard%';" 2>&1 | head -10