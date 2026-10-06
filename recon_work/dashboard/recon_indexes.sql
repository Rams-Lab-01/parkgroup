-- Reconciliation-readiness indexes.
-- These back the dashboard drill-downs and the invoice/payment matching joins.
-- IF NOT EXISTS keeps this idempotent and safe to re-run.

-- Installment matching: payments are matched by date and state.
CREATE INDEX IF NOT EXISTS sale_contract_installment__payment_date_index
  ON sale_contract_installment (payment_date);
CREATE INDEX IF NOT EXISTS sale_contract_installment__due_date_index
  ON sale_contract_installment (due_date);
CREATE INDEX IF NOT EXISTS sale_contract_installment__state_index
  ON sale_contract_installment (state);

-- Dashboard drills filter on these contract columns.
CREATE INDEX IF NOT EXISTS sale_contract__balance_due_index
  ON sale_contract (balance_due);
CREATE INDEX IF NOT EXISTS sale_contract__last_activity_date_index
  ON sale_contract (last_activity_date);
CREATE INDEX IF NOT EXISTS sale_contract__state_index
  ON sale_contract (state);

-- Escrow drills filter on these allocation columns.
CREATE INDEX IF NOT EXISTS escrow_allocation__has_source_data_index
  ON escrow_allocation (has_source_data);
CREATE INDEX IF NOT EXISTS escrow_allocation__variance_amount_index
  ON escrow_allocation (variance_amount);
CREATE INDEX IF NOT EXISTS escrow_allocation__project_id_index
  ON escrow_allocation (project_id);

ANALYZE sale_contract_installment;
ANALYZE sale_contract;
ANALYZE escrow_allocation;
ANALYZE property_details;

\echo ''
\echo '=== indexes now present on reconciliation tables ==='
SELECT tablename, indexname
FROM pg_indexes
WHERE tablename IN ('sale_contract_installment','sale_contract','escrow_allocation')
  AND (indexdef ILIKE '%payment_date%' OR indexdef ILIKE '%due_date%'
       OR indexdef ILIKE '%state%' OR indexdef ILIKE '%balance_due%'
       OR indexdef ILIKE '%last_activity%' OR indexdef ILIKE '%has_source%'
       OR indexdef ILIKE '%variance%' OR indexdef ILIKE '%project_id%')
ORDER BY tablename, indexname;