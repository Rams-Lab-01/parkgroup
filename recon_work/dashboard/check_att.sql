\set ON_ERROR_STOP off
\pset pager off

\echo '=== Asset bundle rows: where is the content? ==='
SELECT id, name, file_size, length(db_datas) AS inline_bytes,
       store_fname, url, public
FROM ir_attachment
WHERE name LIKE 'web.assets_backend%'
ORDER BY id DESC LIMIT 6;

\echo ''
\echo '=== Attachment 7384/7385 detail ==='
SELECT id, name, file_size, length(db_datas) AS inline_bytes, store_fname,
       checksum, public, create_date
FROM ir_attachment WHERE id IN (7382,7383,7384,7385) ORDER BY id;