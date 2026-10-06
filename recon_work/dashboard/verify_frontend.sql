\set ON_ERROR_STOP off
\pset pager off

\echo '=== 1. Dashboard template view in DB ==='
SELECT id, name,
       arch_db::text LIKE '%sgc-kpi-row%'      AS has_kpi_row,
       arch_db::text LIKE '%state.cards.slice%' AS has_card_slices,
       arch_db::text LIKE '%sgc-table%'        AS has_table,
       arch_db::text LIKE '%sgc-watchlist%'    AS has_watchlist
FROM ir_ui_view
WHERE name LIKE '%RentalPropertyDashboard%';

\echo '=== 2. Client action xml_id ==='
SELECT id, module, name FROM ir_model_data
WHERE module = 'sgc_offplan_rental_property_management'
  AND (name LIKE '%dashboard%' OR name = 'property_dashboard');

\echo '=== 3. Asset bundle present ==='
SELECT id, name, "size" AS bytes, url
FROM ir_attachment
WHERE name LIKE 'web.assets_web%'
ORDER BY id DESC LIMIT 5;

\echo '=== 4. Bundle contains new dashboard code? ==='
SELECT id, name,
       strpos(binary::text, '_buildCards')   > 0 AS has_buildcards,
       strpos(binary::text, 'sgc-kpi-row')   > 0 AS has_kpi_row,
       strpos(binary::text, 'RentalPropertyDashboard') > 0 AS has_dashboard
FROM ir_attachment
WHERE name = 'web.assets_web.min.js';

\echo '=== 5. sale.contract list view has new columns ==='
SELECT id, name,
       arch_db::text LIKE '%balance_due%'        AS has_balance_due,
       arch_db::text LIKE '%collection_pct%'     AS has_collection_pct,
       arch_db::text LIKE '%last_activity_date%' AS has_last_activity
FROM ir_ui_view
WHERE model = 'sale.contract' AND type = 'list'
ORDER BY id;

\echo '=== 6. property.project form has geo fields ==='
SELECT id, name, arch_db::text LIKE '%geo_latitude%' AS has_geo
FROM ir_ui_view
WHERE model = 'property.project' AND type = 'form';