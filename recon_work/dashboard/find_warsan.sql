\set ON_ERROR_STOP off
\pset pager off

\echo '=== Find "Warsan" across likely address text columns ==='
SELECT 'property_project.city' AS src, id::text, name, city AS val
FROM property_project WHERE city ILIKE '%warsan%'
UNION ALL
SELECT 'property_project.name', id::text, name, name
FROM property_project WHERE name ILIKE '%warsan%'
UNION ALL
SELECT 'property_details.city', pd.id::text, pr.name, pd.city
FROM property_details pd
  LEFT JOIN property_project pr ON pr.id = pd.project_id
WHERE pd.city ILIKE '%warsan%';

\echo ''
\echo '=== All char text fields on property_details that may hold locality ==='
SELECT name, ttype FROM ir_model_fields
WHERE model = 'property_details' AND ttype IN ('char','text')
ORDER BY name;