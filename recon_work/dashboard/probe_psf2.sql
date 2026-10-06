\set ON_ERROR_STOP off
\pset pager off

\echo '=== sold units: price + area ==='
SELECT count(*) AS units,
       sum(sale_price) AS sum_price,
       round(sum(area)::numeric, 2) AS sum_area,
       round((sum(sale_price)/NULLIF(sum(area),0))::numeric, 2) AS psf
FROM property_details
WHERE state = 'sold';

\echo '=== area nulls/zeros among sold ==='
SELECT count(*) FILTER (WHERE area IS NULL) AS area_null,
       count(*) FILTER (WHERE area = 0) AS area_zero,
       count(*) AS total
FROM property_details WHERE state = 'sold';