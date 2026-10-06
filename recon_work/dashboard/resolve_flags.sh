#!/bin/sh
B=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management
JS="$B/static/src/components/rental_property_dashboard.js"
BUNDLE=/var/lib/odoo/filestore/sgc_mt_parkgroup/7b/7b81de1be7a5b8c7bf1809a6d1d682ac69dd7573

echo "=== our SOURCE file: escrow drill-down lines ==="
grep -n 'viewUnderAllocated\|viewOverAllocated\|viewReconciled' "$JS"

echo ""
echo "=== our SOURCE file: any legacy broken domain pattern? ==="
if grep -n 'required_amount",">"\[' "$JS" || grep -n 'allocated_amount",">"\[' "$JS"; then
  echo "  -> legacy pattern IS in our source"
else
  echo "  -> legacy pattern NOT in our source (good)"
fi

echo ""
echo "=== where does the legacy pattern live in the bundle? ==="
grep -o -b 'required_amount",">",\["allocated_amount' "$BUNDLE" | head -3

echo ""
echo "=== middle-dot encoding in our source vs bundle ==="
echo "  source  :"
grep -o 'units [^<]*sold' "$JS" | head -2
echo "  bundle  :"
grep -o 'units [^"]\{0,40\}sold' "$BUNDLE" | head -3

echo ""
echo "=== bundle: the popup line ==="
grep -o 'sgc-popup__count[^<]\{0,120\}' "$BUNDLE" | head -2