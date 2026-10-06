#!/bin/sh
FS=/var/lib/odoo/filestore/sgc_mt_parkgroup
JS="$FS/7b/7b81de1be7a5b8c7bf1809a6d1d682ac69dd7573"
CSS="$FS/cf/cf6669a9e017809b98e926f2293729fea65f895a"

echo "JS  : $(wc -c < "$JS") bytes"
echo "CSS : $(wc -c < "$CSS") bytes"
echo ""

echo "=== NEW build content probes (the 2026-10-06 fixes) ==="
for probe in 'variance_amount' 'Under-Allocated' 'Over-Allocated' 'units&middot;' 'rec.units' 'rec.city' 'sgc-pin-core'; do
  if grep -qF "$probe" "$JS"; then echo "  FOUND     $probe"; else echo "  MISSING   $probe"; fi
done

echo ""
echo "=== OLD broken patterns must be ABSENT ==="
if grep -qF '["required_amount",">",["allocated_amount","!=",false]]' "$JS"; then
  echo "  FAIL  broken under-allocated domain still present"
else
  echo "  PASS  broken under-allocated domain gone"
fi
if grep -qF '["allocated_amount",">",["required_amount","!=",false]]' "$JS"; then
  echo "  FAIL  broken over-allocated domain still present"
else
  echo "  PASS  broken over-allocated domain gone"
fi

echo ""
echo "=== Core dashboard content ==="
for probe in '_buildCards' 'this.state.cards' 'RentalPropertyDashboard' 'get_development_kpis' 'aging_undated' 'renderMap' 'sgc-kpi-row' 'sgc-watchlist' 'sgc-table' 'sgc-chart'; do
  if grep -qF "$probe" "$JS"; then echo "  FOUND     $probe"; else echo "  MISSING   $probe"; fi
done

echo ""
echo "=== CSS v2 styles ==="
for probe in '.sgc-kpi-row' '.sgc-watchlist' '.sgc-table' '.sgc-map' '.sgc-chart' '.sgc-popup__count'; do
  if grep -qF "$probe" "$CSS"; then echo "  FOUND     $probe"; else echo "  MISSING   $probe"; fi
done