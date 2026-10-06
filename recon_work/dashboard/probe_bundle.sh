#!/bin/sh
FS=/var/lib/odoo/filestore/sgc_mt_parkgroup
JS="$FS/ec/ec92a3f5af2a1c7d6fd1da18caeaeee1d53eba3e"
CSS="$FS/cf/cf6669a9e017809b98e926f2293729fea65f895a"

echo "JS  : $(wc -c < "$JS") bytes"
echo "CSS : $(wc -c < "$CSS") bytes"
echo ""

echo "=== JS content probes ==="
for probe in '_buildCards' 'this.state.cards' 'RentalPropertyDashboard' 'property_dashboard' 'Leaflet' 'echarts' 'aging_undated' 'renderMap' 'get_development_kpis' 'sgc-kpi-row' 'sgc-watchlist' 'sgc-table' 'sgc-chart'; do
  if grep -qF "$probe" "$JS"; then
    echo "  FOUND     $probe  (x$(grep -oF "$probe" "$JS" | wc -l))"
  else
    echo "  MISSING   $probe"
  fi
done

echo ""
echo "=== CSS content probes ==="
for probe in '.sgc-kpi-row' '.sgc-watchlist' '.sgc-table' '.sgc-map' '.sgc-chart' '.sgc-num'; do
  if grep -qF "$probe" "$CSS"; then
    echo "  FOUND     $probe"
  else
    echo "  MISSING   $probe"
  fi
done

echo ""
echo "=== placeholder markers in JS ==="
if grep -oE 'TODO|FIXME|Lorem ipsum|DUMMY|SAMPLE_DATA' "$JS" | sort | uniq -c; then
  echo "  (above are marker counts)"
else
  echo "  clean - none found"
fi

echo ""
echo "=== our module files referenced in bundle header ==="
grep -oE 'sgc_offplan_rental_property_management/static/src/[a-z/_.]*' "$JS" | sort -u