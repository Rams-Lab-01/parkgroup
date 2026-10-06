\echo '===== unit_type distribution ====='
SELECT unit_type, count(*) FROM property_details GROUP BY 1 ORDER BY 2 DESC;
\echo '===== sold aggregates ====='
SELECT round(sum(d.sale_price),2) AS sell_sum, round(sum(sc.total_paid),2) AS paid_sum, count(*) AS contracts
FROM sale_contract sc JOIN property_details d ON d.id=sc.property_id;
\echo '===== PSF and areas ====='
SELECT round(sum(d.sale_price)/nullif(sum(d.area),0),2) AS psf_sold, round(sum(d.area),2) AS area_sold, count(*) AS sold_units FROM property_details d WHERE d.state='sold';
SELECT round(sum(d.area),2) AS area_all, count(*) AS all_units, round(avg(d.area),2) AS avg_area FROM property_details d;
\echo '===== avg unit size sold ====='
SELECT round(avg(d.area),2) AS avg_area_sold FROM property_details d WHERE d.state='sold';
\echo '===== admin fees ====='
SELECT round(sum(d.admin_fee),2) AS admin_fee_sum FROM property_details d WHERE d.state='sold';
SELECT round(sum(d.admin_fee),2) FROM property_details d;
\echo '===== admin fee sample ====='
SELECT admin_fee, count(*) FROM property_details GROUP BY 1 ORDER BY 2 DESC LIMIT 8;
\echo '===== sold per project with area ====='
SELECT p.code, count(*), round(sum(d.sale_price),2), round(sum(d.area),2)
FROM property_details d JOIN property_project p ON p.id=d.project_id
WHERE d.state='sold' GROUP BY 1 ORDER BY 1;
