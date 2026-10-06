#!/bin/sh
JS=/var/lib/odoo/filestore/sgc_mt_parkgroup/d9/d93bdb548610302db6d4d643374a9facea19ab77
CSS=/var/lib/odoo/filestore/sgc_mt_parkgroup/cf/cf6669a9e017809b98e926f2293729fea65f895a

echo "JS  : $(wc -c < "$JS") bytes"
echo "CSS : $(wc -c < "$CSS") bytes"
echo ""

echo "=== watchlist_counts consumption (the newest fix) ==="
for probe in 'watchlist_counts' 'wc.reconciled' 'wc.under_allocated' 'wc.over_allocated' 'wc.awaiting_source'; do
  if grep -qF "$probe" "$JS"; then echo "  FOUND     $probe"; else echo "  MISSING   $probe"; fi
done

echo ""
echo "=== watchlist counts must NOT be hardcoded 0 ==="
grep -o 'this.state.watchlist=\[.\{0,700\}' "$JS" | head -1

echo ""
echo "=== ALL legacy broken domains must be ABSENT ==="
for bad in '["required_amount",">",["allocated_amount","!=",false]]' \
           '["allocated_amount",">",["required_amount","!=",false]]' \
           '["required_amount","<",["allocated_amount","!=",false]]'; do
  if grep -qF "$bad" "$JS"; then echo "  FAIL   present: $bad"; else echo "  PASS   absent:  $bad"; fi
done

echo ""
echo "=== variance_amount domains present ==="
grep -o '\[\["variance_amount","[<>=\[]*",[^]]*\]\]' "$JS" | sort -u | sed 's/^/  /'

echo ""
echo "=== hardcoded-zero watchlist entries ==="
if grep -o 'label:"[^"]*",count:0,' "$JS"; then
  echo "  FAIL  hardcoded count:0 found"
else
  echo "  PASS  no hardcoded count:0 in watchlist"
fi

echo ""
echo "=== core dashboard content ==="
for probe in '_buildCards' 'this.state.cards' 'RentalPropertyDashboard' 'get_development_kpis' 'aging_undated' 'renderMap' 'sgc-kpi-row' 'sgc-watchlist' 'sgc-table' 'sgc-chart'; do
  if grep -qF "$probe" "$JS"; then echo "  FOUND     $probe"; else echo "  MISSING   $probe"; fi
done

echo ""
echo "=== CSS v2 ==="
for probe in '.sgc-kpi-row' '.sgc-watchlist' '.sgc-table' '.sgc-map' '.sgc-chart'; do
  if grep -qF "$probe" "$CSS"; then echo "  FOUND     $probe"; else echo "  MISSING   $probe"; fi
done