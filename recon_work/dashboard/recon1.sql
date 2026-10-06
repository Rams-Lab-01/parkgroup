-- Recon script: schema + data shape for dashboard KPIs
\echo '===== TABLES matching ====='
SELECT table_name FROM information_schema.tables
WHERE table_schema='public' AND (
  table_name LIKE '%installment%' OR table_name LIKE '%escrow%'
  OR table_name LIKE '%sale_contract%' OR table_name LIKE '%commission%'
  OR table_name LIKE '%milestone%' OR table_name LIKE '%project%')
ORDER BY table_name;

\echo '===== sale_contract columns ====='
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name='sale_contract' ORDER BY ordinal_position;

\echo '===== installment table columns ====='
SELECT table_name, column_name, data_type FROM information_schema.columns
WHERE table_name LIKE '%installment%' ORDER BY table_name, ordinal_position;
