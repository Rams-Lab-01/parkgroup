\echo '== company currency =='
SELECT c.name AS company, r.name AS currency, r.symbol, r.position
FROM res_company c JOIN res_currency r ON r.id = c.currency_id;
\echo '== contracts by escrow_project_id =='
SELECT escrow_project_id, count(*), round(sum(total_paid)::numeric,2)
FROM sale_contract GROUP BY 1 ORDER BY 1;
\echo '== GOLF contracts escrow link =='
SELECT sc.id, sc.name, sc.escrow_project_id, d.unit_number
FROM sale_contract sc JOIN property_details d ON d.id=sc.property_id
JOIN property_project p ON p.id=d.project_id WHERE p.code='GOLF';
