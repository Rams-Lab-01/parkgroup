#!/bin/bash
# Concurrency stress: 4 simultaneous KPI computations, each on its own Odoo shell.
B=/opt/odoo/deploy/sgc-rent-mt

cat > /tmp/conc_kpi.py <<'PY'
import time
t0 = time.time()
pd = env['property.details'].sudo().search([], limit=1)
p = pd.get_development_kpis()
dt = time.time() - t0
print('WORKER_DONE %.2fs units=%s sold=%s balance=%s recon=%s' % (
    dt, p['total_units'], p['sold_units'], p['balance_due'], p['recon_rate']))
env.cr.rollback()
PY

cp /tmp/conc_kpi.py $B/conc_kpi.py

echo "launching 4 concurrent workers ..."
START=$(date +%s.%N)
for i in 1 2 3 4; do
  ( docker exec -i sgc_rent_mt odoo shell -d sgc_mt_parkgroup --no-http \
      < $B/conc_kpi.py 2>/dev/null | grep WORKER_DONE > /tmp/conc_$i.out ) &
done
wait
END=$(date +%s.%N)
echo "wall clock: $(echo "$END - $START" | bc)s"
echo ""
for i in 1 2 3 4; do
  printf 'worker %s: ' $i
  cat /tmp/conc_$i.out
done

echo ""
echo "=== parallel read-only SQL load (10 concurrent readers) ==="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -c "
SELECT
  (SELECT count(*) FROM property_details) AS units,
  (SELECT count(*) FROM sale_contract) AS contracts,
  (SELECT count(*) FROM sale_contract_installment) AS installments,
  (SELECT count(*) FROM escrow_allocation) AS allocations;" 2>&1 | head -6

echo ""
echo "=== table sizes ==="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -c "
SELECT relname, n_live_tup FROM pg_stat_user_tables
WHERE relname IN ('property_details','sale_contract','sale_contract_installment','escrow_allocation','property_project')
ORDER BY n_live_tup DESC;"