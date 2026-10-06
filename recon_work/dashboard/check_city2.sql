\set ON_ERROR_STOP off
\pset pager off

\echo '=== Park Group projects with full location context ==='
SELECT p.id, p.name, p.city, s.name AS emirate, c.name AS country,
       p.geo_latitude, p.geo_longitude
FROM property_project p
LEFT JOIN res_country_state s ON s.id = p.state_id
LEFT JOIN res_country c ON c.id = p.country_id
ORDER BY p.name;

\echo ''
\echo '=== Address / location text fields available on property.project ==='
SELECT name, ttype FROM ir_model_fields
WHERE model = 'property.project' AND ttype = 'char'
  AND (name ILIKE '%addr%' OR name ILIKE '%locat%' OR name ILIKE '%area%'
       OR name ILIKE '%communit%' OR name ILIKE '%city%' OR name ILIKE '%region%')
ORDER BY name;