\set ON_ERROR_STOP off
\pset pager off

\echo '=== NEW COLUMNS ON sale_contract ==='
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'sale_contract'
  AND column_name IN ('balance_due','collection_pct','last_activity_date')
ORDER BY column_name;

\echo '=== NEW COLUMNS ON property_project ==='
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'property_project'
  AND column_name IN ('geo_latitude','geo_longitude')
ORDER BY column_name;

\echo '=== PROJECTS (id, code, name, geo) ==='
SELECT id, code, name, geo_latitude, geo_longitude
FROM property_project
ORDER BY id;