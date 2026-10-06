\set ON_ERROR_STOP off
\pset pager off
\echo '=== module version recorded in DB ==='
SELECT name, state, latest_version, install_date::date AS installed
FROM ir_module_module
WHERE name = 'sgc_offplan_rental_property_management';

\echo ''
\echo '=== template DB must be untouched ==='
SELECT datname FROM pg_database WHERE datname LIKE 'sgc_mt%';
SELECT datname, datistemplate, datallowconn FROM pg_database
WHERE datname = 'sgc_mt_template';

\echo ''
\echo '=== dashboard client action + menu ==='
SELECT d.name AS xml_id, a.tag, a.name
FROM ir_model_data d JOIN ir_act_client a ON a.id = d.res_id
WHERE d.module = 'sgc_offplan_rental_property_management'
  AND d.name = 'action_property_dashboard';

\echo ''
\echo '=== final Park Group project data ==='
SELECT name, city, geo_latitude, geo_longitude
FROM property_project ORDER BY name;