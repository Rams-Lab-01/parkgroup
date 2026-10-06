\set ON_ERROR_STOP off
\pset pager off
\echo '=== current asset bundles (filestore paths) ==='
SELECT id, name, file_size, store_fname, url
FROM ir_attachment
WHERE name LIKE 'web.assets_backend.%'
ORDER BY id DESC;