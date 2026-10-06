#!/bin/bash
CSSFILE=/opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management/static/src/components/rental_property_dashboard.css
BUILT=/var/lib/odoo/filestore/sgc_mt_parkgroup/cf/cf6669a9e017809b98e926f2293729fea65f895a

echo "=========== SOURCE css ==========="
echo ":has( count        : $(grep -c ':has(' $CSSFILE)"
echo "--sgc-* DECLARED   : $(grep -cE '^\s*--sgc-[a-z-]+ *:' $CSSFILE)"
echo "--sgc-* REFERENCED : $(grep -oE 'var\(--sgc-[a-z-]+' $CSSFILE | sort -u | tr '\n' ' ')"
echo ""
echo "referenced but NEVER declared:"
comm -13 <(grep -oE '^\s*--sgc-[a-z-]+' $CSSFILE | tr -d ' ' | sort -u) \
         <(grep -oE 'var\(--sgc-[a-z-]+' $CSSFILE | sed 's/var(//' | sort -u)

echo ""
echo "=========== BUILT bundle css ==========="
if [ -f "$BUILT" ]; then
  echo "size: $(wc -c < $BUILT)"
  echo ":has( survived minify : $(grep -c ':has(' $BUILT)"
  echo "data-theme survived   : $(grep -c 'data-theme' $BUILT)"
  echo "surface-base survived : $(grep -c 'surface-base' $BUILT)"
  echo "sgc-re-dashboard      : $(grep -c 'sgc-re-dashboard' $BUILT)"
else
  echo "BUILT file not found at $BUILT"
fi

echo ""
echo "=========== JS: every this.env usage ==========="
grep -n 'this\.env\.' /opt/odoo/deploy/sgc-rent-mt/addons/sgc_offplan_rental_property_management/static/src/components/rental_property_dashboard.js

echo ""
echo "=========== property_details.state values (card drill domains) ==========="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -c \
"SELECT state, count(*) FROM property_details GROUP BY state ORDER BY 2 DESC;" 2>&1 | head -12