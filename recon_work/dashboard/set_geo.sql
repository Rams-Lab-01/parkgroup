-- Park Group developments - coordinates derived from DB address field + user confirmation.
-- NOTE: these are approximate area centroids, intended to be refined by the user
--       in the Odoo project form (geo_latitude / geo_longitude).
-- RES  -> Warsan 4, Ras Al Khaimah  (NOTE: property_project.city wrongly says 'Dubai')
-- GOLF -> Al Zorah, Ajman
-- BR1  -> Al Marjan Island, Ras Al Khaimah
-- BR2  -> Al Marjan Island, Ras Al Khaimah
UPDATE property_project SET geo_latitude = 25.8090, geo_longitude = 55.9420 WHERE code = 'RES';
UPDATE property_project SET geo_latitude = 25.4120, geo_longitude = 55.5290 WHERE code = 'GOLF';
UPDATE property_project SET geo_latitude = 25.8560, geo_longitude = 55.9820 WHERE code = 'BR1';
UPDATE property_project SET geo_latitude = 25.8565, geo_longitude = 55.9835 WHERE code = 'BR2';

SELECT id, code, name, city, address, geo_latitude, geo_longitude
FROM property_project ORDER BY id;