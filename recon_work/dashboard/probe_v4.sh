#!/bin/sh
JS=/var/lib/odoo/filestore/sgc_mt_parkgroup/14/14c5e90a984ecafaea0b76614cab251bf48304d3
CSS=/var/lib/odoo/filestore/sgc_mt_parkgroup/cf/cf6669a9e017809b98e926f2293729fea65f895a

echo "JS  : $(wc -c < "$JS") bytes"
echo "CSS : $(wc -c < "$CSS") bytes"
echo ""

echo "=== CORRECTED SIGN SEMANTICS (must all be present) ==="
for probe in 'variance_amount","<",-0.01' 'variance_amount",">",0.01' \
             'viewOutstanding' 'viewAllAllocations' 'viewWithSource' \
             'watchlist_counts' 'wc.under_allocated' 'wc.over_allocated' \
             '"Outstanding Balance"' '"Escrow Allocations"' '"Allocations With Source"'; do
  if grep -qF "$probe" "$JS"; then echo "  FOUND     $probe"; else echo "  *** MISSING ***  $probe"; fi
done

echo ""
echo "=== drill-down bodies as served ==="
grep -o 'viewUnderAllocated(){[^}]*}' "$JS"
grep -o 'viewOverAllocated(){[^}]*}' "$JS"
grep -o 'viewOutstanding(){[^}]*}' "$JS"
grep -o 'viewAllAllocations(){[^}]*}' "$JS"
grep -o 'viewWithSource(){[^}]*}' "$JS"

echo ""
echo "=== watchlist as served ==="
grep -o 'this.state.watchlist=\[.\{0,420\}' "$JS"

echo ""
echo "=== card -> escrow action wiring as served ==="
grep -o 'label:"[A-Za-z ]*",value:money(payload\.\(required_escrow\|allocated_escrow\|escrow_shortfall\))[^}]*}' "$JS"
grep -o 'label:"Balance Due"[^}]*}' "$JS"

echo ""
echo "=== NO stale/wrong patterns ==="
for bad in 'label:"Under-allocated",count:wc.under_allocated||0,domain:[["variance_amount",">",0.01]]' \
           'label:"Over-allocated",count:wc.over_allocated||0,domain:[["variance_amount","<",-0.01]]' \
           '"Escrow Shortfall",value:money(payload.escrow_shortfall),sub:"Required - Allocated",icon:ICON.alert,action:"viewOverAllocated"' \
           '"Balance Due",value:money(payload.balance_due),sub:"Still outstanding",icon:ICON.money,action:"viewAgedOverdue"'; do
  if grep -qF "$bad" "$JS"; then echo "  *** STALE *** $bad"; else echo "  PASS clean: ${bad:0:58}..."; fi
done