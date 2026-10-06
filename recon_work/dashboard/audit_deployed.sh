#!/bin/sh
B=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management
JS="$B/static/src/components/rental_property_dashboard.js"
CSS="$B/static/src/components/rental_property_dashboard.css"
TPL="$B/static/src/xml/template.xml"
PY="$B/models/core/property_details.py"

echo "=== deployed source audit ==="
for f in "$JS" "$CSS" "$TPL" "$PY"; do
  printf '%-52s %s bytes\n' "${f#$B/}" "$(wc -c < "$f")"
done

echo ""
echo "=== placeholder / stub markers in OUR deployed sources ==="
if grep -nE 'TODO|FIXME|XXX|DUMMY|Lorem ipsum|SAMPLE_DATA|PLACEHOLDER_|\bstub\b|not implemented' "$JS" "$TPL" "$PY"; then
  echo "  ^ markers found (review above)"
else
  echo "  CLEAN - no TODO/FIXME/stub/placeholder markers in JS, template, or server model"
fi

echo ""
echo "=== JS structure ==="
echo "  registrations       : $(grep -c 'dashboardActions.add' "$JS")"
echo "  _buildCards defs    : $(grep -c '_buildCards(payload)' "$JS")"
echo "  state.cards assigns : $(grep -c 'this.state.cards =' "$JS")"
echo "  renderMap defs      : $(grep -c 'renderMap()' "$JS")"
echo "  onWillStart/Setup   : $(grep -c 'onWillStart\|setup()' "$JS")"

echo ""
echo "=== template refs vs JS useRef (must match) ==="
echo "  t-ref in template:"
grep -oE 't-ref="[a-zA-Z]+"' "$TPL" | sort -u | sed 's/^/     /'
echo "  useRef in JS:"
grep -oE 'useRef\("[a-zA-Z]+"\)' "$JS" | sort -u | sed 's/^/     /'

echo ""
echo "=== server KPI method present ==="
grep -n 'def get_development_kpis' "$PY" | sed 's/^/  /'
grep -n "'aging_buckets'\|'undated_balance'\|'watchlist'\|'projects'\|'map'" "$PY" | head -10 | sed 's/^/  /'