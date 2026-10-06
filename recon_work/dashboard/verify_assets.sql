\set ON_ERROR_STOP off
\pset pager off

\echo '=== Attachments for dashboard static files ==='
SELECT id, name, file_size, mimetype, url, create_date
FROM ir_attachment
WHERE url ILIKE '%rental_property_dashboard%'
ORDER BY id;

\echo '=== Does any stored blob contain our new card builder? ==='
SELECT id, name, file_size,
       strpos(convert_from(db_datas, 'UTF8'), '_buildCards') > 0 AS has_buildcards,
       strpos(convert_from(db_datas, 'UTF8'), 'sgc-kpi-row') > 0 AS has_kpi_row
FROM ir_attachment
WHERE db_datas IS NOT NULL
  AND mimetype ILIKE '%javascript%'
  AND (strpos(convert_from(db_datas, 'UTF8'), 'RentalPropertyDashboard') > 0
       OR strpos(convert_from(db_datas, 'UTF8'), 'property_dashboard') > 0)
ORDER BY id DESC
LIMIT 5;

\echo '=== Bundle attachments (rebuilt after purge?) ==='
SELECT id, name, file_size, create_date
FROM ir_attachment
WHERE name LIKE 'web.assets%'
ORDER BY id DESC LIMIT 6;