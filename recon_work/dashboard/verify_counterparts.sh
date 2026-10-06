#!/bin/bash
A=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management

echo "=== root-level files: counterpart exists elsewhere? referenced by manifest? ==="
printf '%-58s %-10s %-8s %s\n' "FILE" "SIZE" "REF'D" "COUNTERPART"
for f in "$A"/*.xml "$A"/*.py; do
  [ -f "$f" ] || continue
  b=$(basename "$f")
  case "$b" in __init__.py|__manifest__.py) continue;; esac
  sz=$(wc -c < "$f")
  if grep -q "\"$b\"" "$A/__manifest__.py" 2>/dev/null; then ref="YES"; else ref="no"; fi
  cp_path=$(find "$A" -name "$b" -not -path '*__pycache__*' -not -path "$A/$b" 2>/dev/null | head -1)
  if [ -n "$cp_path" ]; then cp="${cp_path#$A/}"; else cp="-- NONE --"; fi
  printf '%-58s %-10s %-8s %s\n' "$b" "$sz" "$ref" "$cp"
done

echo ""
echo "=== backup / rename artifacts ==="
find "$A" -maxdepth 1 \( -name '*.bak-*' -o -name '*.rename-*' \) -print0 2>/dev/null | xargs -0 -I{} sh -c 'printf "  %-60s %s bytes\n" "$(basename "{}")" "$(wc -c < "{}" 2>/dev/null || echo DIR)"'

echo ""
echo "=== what does report.bak-20260923 actually look like? ==="
ls -ld "$A/report.bak-20260923" 2>/dev/null && find "$A/report.bak-20260923" -type f | head -5