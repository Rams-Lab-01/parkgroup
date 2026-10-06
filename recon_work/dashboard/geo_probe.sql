\set ON_ERROR_STOP off
\pset pager off

\echo '=== ANY lat/lon COLUMNS IN SCHEMA ==='
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE (column_name ILIKE '%lat%' OR column_name ILIKE '%lon%'
       OR column_name ILIKE '%geo%' OR column_name ILIKE '%coord%')
  AND table_schema = 'public'
ORDER BY table_name, column_name;

\echo '=== property_res_city COLUMNS ==='
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'property_res_city' ORDER BY ordinal_position;

\echo '=== property_res_city ROWS ==='
SELECT * FROM property_res_city LIMIT 20;

\echo '=== property_project COLUMNS ==='
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'property_project' ORDER BY ordinal_position;