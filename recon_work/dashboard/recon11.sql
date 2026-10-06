\echo '===== PSF / areas (numeric casts) ====='
SELECT round((sum(d.sale_price)/nullif(sum(d.area),0))::numeric, 2) AS psf_sold,
       round(sum(d.area)::numeric, 2) AS area_sold, count(*) AS sold_units
FROM property_details d WHERE d.state='sold';
\echo '===== all units area ====='
SELECT round(sum(d.area)::numeric,2) AS area_all, count(*) AS all_units, round(avg(d.area)::numeric,2) AS avg_area
FROM property_details d;
\echo '===== sold avg area ====='
SELECT round(avg(d.area)::numeric,2) AS avg_area_sold FROM property_details d WHERE d.state='sold';
\echo '===== per project sold+area ====='
SELECT p.code, count(*) AS sold, round(sum(d.sale_price)::numeric,2) AS value, round(sum(d.area)::numeric,0) AS area
FROM property_details d JOIN property_project p ON p.id=d.project_id
WHERE d.state='sold' GROUP BY 1 ORDER BY 1;
\echo '===== available area ====='
SELECT round(sum(d.area)::numeric,0) FROM property_details d WHERE d.state='available';
\echo '===== unit mix sold ====='
SELECT unit_type, count(*) FROM property_details WHERE state='sold' GROUP BY 1 ORDER BY 2 DESC;
