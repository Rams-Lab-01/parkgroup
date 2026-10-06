\set ON_ERROR_STOP off
\pset pager off

\echo '=== All ir_ui_view rows mentioning RentalPropertyDashboard ==='
SELECT id, name, model, key, priority, active
FROM ir_ui_view
WHERE name ILIKE '%rentalproperty%'
   OR arch_db::text LIKE '%RentalPropertyDashboard%'
ORDER BY id;

\echo '=== ir_model_data for dashboard template ==='
SELECT id, module, name, model, res_id
FROM ir_model_data
WHERE module = 'sgc_offplan_rental_property_management'
  AND name ILIKE '%dashboard%'
ORDER BY name;

\echo '=== attachment columns (to find size/binary) ==='
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'ir_attachment'
ORDER BY ordinal_position;