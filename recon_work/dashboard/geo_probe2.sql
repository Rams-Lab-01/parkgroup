\set ON_ERROR_STOP off
\pset pager off

\echo '=== PROJECT city / state / address ==='
SELECT id, code, name, city, state_id, country_id, address
FROM property_project ORDER BY id;

\echo '=== STATE (res.country.state) ==='
SELECT id, name, code FROM res_country_state ORDER BY id;

\echo '=== PARTNERS WITH GEO DATA (non-zero) ==='
SELECT id, name, partner_latitude, partner_longitude, city, country_id
FROM res_partner
WHERE COALESCE(partner_latitude,0) <> 0 OR COALESCE(partner_longitude,0) <> 0
ORDER BY id;

\echo '=== PARTNER COMPANY (developer) ==='
SELECT p.id, p.name, p.partner_latitude, p.partner_longitude, p.city, p.country_id
FROM res_partner p
WHERE p.is_company = true
ORDER BY p.id;