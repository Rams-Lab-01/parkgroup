\set ON_ERROR_STOP off
\pset pager off

\echo '=== sale.contract.installment COLUMNS ==='
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'sale_contract_installment'
ORDER BY ordinal_position;

\echo '=== sale_contract COLUMNS (relevant) ==='
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'sale_contract'
  AND (column_name ILIKE '%company%' OR column_name ILIKE '%paid%'
       OR column_name ILIKE '%price%' OR column_name ILIKE '%date%'
       OR column_name ILIKE '%state%' OR column_name ILIKE '%property%')
ORDER BY column_name;

\echo '=== escrow.allocation COLUMNS ==='
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'escrow_allocation'
ORDER BY ordinal_position;