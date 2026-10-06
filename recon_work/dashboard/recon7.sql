\copy (SELECT p.code AS proj, d.unit_number AS unit, sc.id AS contract_id, sc.sale_price, coalesce(sc.total_paid,0) AS total_paid, (SELECT max(i.payment_date) FROM sale_contract_installment i WHERE i.contract_id=sc.id AND i.state='paid') AS last_pay, sc.contract_date, (SELECT max(i.due_date) FROM sale_contract_installment i WHERE i.contract_id=sc.id) AS last_due) TO '/tmp/dash_contracts.csv' WITH CSV HEADER;
\echo '===== commission_line columns ====='
SELECT string_agg(column_name, ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='commission_line';
\echo '===== commission counts ====='
SELECT count(*) FROM commission_line;
\echo '===== property_commission_line ====='
SELECT count(*) FROM property_commission_line;
\echo '===== project_milestone ====='
SELECT count(*) FROM project_milestone;
\echo '===== milestone columns ====='
SELECT string_agg(column_name, ', ' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='project_milestone';
\echo '===== res_partner user_type ====='
SELECT user_type, count(*) FROM res_partner WHERE active GROUP BY 1 ORDER BY 2 DESC;
