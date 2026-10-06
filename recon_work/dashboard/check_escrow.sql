\set ON_ERROR_STOP off
\pset pager off

\echo '=== escrow.allocation money fields ==='
SELECT name, ttype, field_description->>'en_US' AS descr
FROM ir_model_fields
WHERE model = 'escrow.allocation'
  AND name IN ('required_amount','allocated_amount','variance_amount','has_source_data')
ORDER BY name;

\echo ''
\echo '=== does variance_amount = required - allocated? sanity check ==='
SELECT count(*) AS total,
       count(*) FILTER (WHERE abs(variance_amount - (required_amount - allocated_amount)) < 0.01) AS matches_diff,
       count(*) FILTER (WHERE variance_amount > 0.01)  AS under_allocated,
       count(*) FILTER (WHERE variance_amount < -0.01) AS over_allocated,
       count(*) FILTER (WHERE has_source_data)          AS with_source
FROM escrow_allocation;