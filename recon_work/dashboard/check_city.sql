\set ON_ERROR_STOP off
\pset pager off

\echo '=== Park Group projects: location fields ==='
SELECT id, name, city, country_id->>'en_US' AS country, state_id->>'en_US' AS emirate
FROM property_project
ORDER BY name;

\echo ''
\echo '=== city field type on property.project ==='
SELECT name, ttype, relation
FROM ir_model_fields
WHERE model = 'property.project'
  AND name IN ('city', 'state_id', 'country_id', 'geo_latitude', 'geo_longitude');

\echo ''
\echo '=== distinct city values in use ==='
SELECT city, count(*) FROM property_project
WHERE city IS NOT NULL AND city <> ''
GROUP BY city ORDER BY 2 DESC;

\echo ''
\echo '=== res.city rows for the UAE emirates involved ==='
SELECT name FROM res_city
WHERE name ILIKE '%khaimah%' OR name ILIKE '%ajman%' OR name ILIKE '%dubai%' OR name ILIKE '%zorah%'
ORDER BY name;