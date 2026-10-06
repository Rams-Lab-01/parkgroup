\set ON_ERROR_STOP off
\pset pager off

\echo '=== installment model: fields relevant to accounting matching ==='
SELECT name, ttype, relation, store IS NOT TRUE AS computed
FROM ir_model_fields
WHERE model = 'sale.contract.installment'
ORDER BY name;

\echo ''
\echo '=== sale.contract: accounting linkage fields ==='
SELECT name, ttype, relation
FROM ir_model_fields
WHERE model = 'sale.contract'
  AND (name ILIKE '%invoice%' OR name ILIKE '%payment%' OR name ILIKE '%journal%'
       OR name ILIKE '%move%' OR name ILIKE '%total_paid%' OR name ILIKE '%balance%')
ORDER BY name;

\echo ''
\echo '=== escrow models present ==='
SELECT model, name->>'en_US' AS label FROM ir_model
WHERE model LIKE 'escrow%' ORDER BY model;

\echo ''
\echo '=== escrow.release fields ==='
SELECT name, ttype, relation FROM ir_model_fields
WHERE model LIKE 'escrow.release' ORDER BY name;