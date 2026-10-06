\set ON_ERROR_STOP off
\pset pager off
\echo '=== module state ==='
SELECT name, state, latest_version
FROM ir_module_module
WHERE name = 'sgc_offplan_rental_property_management';

\echo ''
\echo '=== asset bundles present (fresh) ==='
SELECT id, name, file_size, url
FROM ir_attachment
WHERE name LIKE 'web.assets_backend.%'
ORDER BY id;