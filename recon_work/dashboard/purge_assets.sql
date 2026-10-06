-- Purge web asset attachments so the dashboard JS/XML/CSS bundle is rebuilt.
-- NOTE: backend bundle is named web.assets_backend.min.js / .css (NOT web.assets_web).
DELETE FROM ir_attachment
WHERE (url LIKE '%rental_property_dashboard%'
       OR name LIKE 'web.assets_web.%'
       OR name LIKE 'web.assets_backend.%'
       OR name LIKE 'web.assets_frontend.%')
RETURNING id, name, file_size;

SELECT count(*) AS remaining_asset_bundles
FROM ir_attachment
WHERE name LIKE 'web.assets_web.%'
   OR name LIKE 'web.assets_backend.%'
   OR name LIKE 'web.assets_frontend.%';

SELECT count(*) AS remaining_dashboard_assets
FROM ir_attachment
WHERE url LIKE '%rental_property_dashboard%';