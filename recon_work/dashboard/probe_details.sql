\set ON_ERROR_STOP off
\pset pager off
\echo '=== property.details columns we rely on ==='
SELECT column_name, data_type FROM information_schema.columns
WHERE table_name = 'property_details'
  AND column_name IN ('admin_fee','company_id','project_id','state','unit_type',
                      'total_area','sale_price','property_size','area')
ORDER BY column_name;

\echo '=== property.details state values ==='
SELECT state, count(*) FROM property_details GROUP BY state ORDER BY state;

\echo '=== property.details unit_type values ==='
SELECT unit_type, count(*) FROM property_details GROUP BY unit_type ORDER BY unit_type;