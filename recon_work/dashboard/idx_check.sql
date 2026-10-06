\set ON_ERROR_STOP off
\pset pager off

\echo '=== existing indexes on reconciliation-relevant tables ==='
SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE tablename IN ('sale_contract_installment','sale_contract','escrow_allocation','property_details')
  AND (indexdef ILIKE '%invoice%' OR indexdef ILIKE '%payment_date%' OR indexdef ILIKE '%due_date%'
       OR indexdef ILIKE '%contract_id%' OR indexdef ILIKE '%variance%' OR indexdef ILIKE '%has_source%'
       OR indexdef ILIKE '%balance_due%' OR indexdef ILIKE '%last_activity%' OR indexdef ILIKE '%state%')
ORDER BY tablename, indexname;

\echo ''
\echo '=== tables lacking ANY index on the join keys (summary) ==='
SELECT t.tablename, count(i.indexname) AS idx_count
FROM pg_tables t
LEFT JOIN pg_indexes i ON i.tablename = t.tablename
WHERE t.tablename IN ('sale_contract_installment','sale_contract','escrow_allocation','property_details','property_project')
GROUP BY t.tablename ORDER BY t.tablename;