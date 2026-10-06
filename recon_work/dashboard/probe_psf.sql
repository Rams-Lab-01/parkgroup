\set ON_ERROR_STOP off
\pset pager off

\echo '=== sale.contract state values ==='
SELECT state, count(*), sum(sale_price) AS total_price, sum(total_paid) AS total_paid
FROM sale_contract GROUP BY state ORDER BY state;

\echo '=== sold property.details: area + price (for real PSF) ==='
SELECT count(*) AS units,
       sum(sale_price) AS sum_price,
       sum(area) AS sum_area,
       round(sum(sale_price)/NULLIF(sum(area),0), 2) AS psf
FROM property_details
WHERE state = 'sold';

\echo '=== cross-check: contracts linked to sold units ==='
SELECT count(*) AS contracts, sum(sc.sale_price) AS price, sum(sc.total_paid) AS paid
FROM sale_contract sc
JOIN property_details pd ON pd.id = sc.property_id
WHERE pd.state = 'sold';

\echo '=== installment states ==='
SELECT state, count(*), sum(amount) FROM sale_contract_installment GROUP BY state ORDER BY state;