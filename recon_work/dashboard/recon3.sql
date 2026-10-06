\echo '===== escrow_allocation summary ====='
SELECT count(*) AS cnt,
  count(*) FILTER (WHERE has_source_data) AS with_source,
  count(*) FILTER (WHERE reconciled) AS reconciled_cnt,
  round(sum(required_amount)) AS required_sum,
  round(sum(allocated_amount)) AS allocated_sum,
  round(sum(variance_amount)) AS variance_sum,
  round(sum(collected_amount)) AS collected_sum,
  count(DISTINCT project_id) AS projects
FROM escrow_allocation;

\echo '===== escrow_allocation per project ====='
SELECT a.project_id, p.code, count(*) AS cnt,
  round(sum(a.required_amount)) AS required, round(sum(a.allocated_amount)) AS allocated,
  round(sum(a.variance_amount)) AS variance,
  count(*) FILTER (WHERE a.has_source_data) AS src,
  count(*) FILTER (WHERE a.reconciled) AS rec
FROM escrow_allocation a LEFT JOIN property_project p ON p.id = a.project_id
GROUP BY 1,2 ORDER BY 1;

\echo '===== property_project geo ====='
SELECT id, code, city, state_id, country_id, left(coalesce(address,''),60) AS addr FROM property_project ORDER BY code;

\echo '===== handover ====='
SELECT count(*) FILTER (WHERE handover_date IS NOT NULL) AS with_handover, min(handover_date), max(handover_date) FROM sale_contract;

\echo '===== installment sample ====='
SELECT id, contract_id, sequence, name, state, due_date, payment_date, amount, percentage FROM sale_contract_installment ORDER BY contract_id, sequence LIMIT 12;

\echo '===== payment schedule tables ====='
SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name LIKE '%payment_schedule%';

\echo '===== property_details columns ====='
SELECT string_agg(column_name, ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='property_details';

\echo '===== sale_contract escrow link ====='
SELECT id, name, escrow_project_id FROM sale_contract LIMIT 4;

\echo '===== escrow_release count ====='
SELECT count(*) FROM escrow_release;
