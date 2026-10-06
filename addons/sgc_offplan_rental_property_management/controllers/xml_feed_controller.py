# -*- coding: utf-8 -*-
#
# Listing Syndication — Outbound Feed
# ------------------------------------------------------------------
# This module generates a structurally-correct, well-formed XML listing
# feed for Bayut / Property Finder / Dubizzle / Houza / Property Monitor
# style consumers, built from `property.details` records.
#
# CREDENTIAL GAP (intentional, not a bug): there are no live API
# credentials/partner agreements with Bayut, Property Finder, or
# Dubizzle yet. The exact field names/XSD each portal expects can only
# be confirmed once a partner agreement is in place. This feed uses a
# single generic schema modeled on the field set that is common across
# all of these portals' publicly documented listing feeds (reference,
# title, description, type, location, price/rent, beds/baths, area,
# images, agent contact). When real credentials and field-mapping docs
# arrive, swap `_build_property_element` field names/structure to match
# — the property.details -> feed pipeline itself does not need to
# change.
from odoo import http, fields, _
from odoo.http import request
from odoo.tools import html2plaintext
import hmac
import logging
import xml.etree.ElementTree as ET

_logger = logging.getLogger(__name__)

# property.details.state values considered listable on a syndication feed.
# "published/available" per spec — sold/under-maintenance units are never
# advertised on external portals.
_LISTABLE_STATES = ("available", "rented")

# property.details.property_type -> feed vocabulary (currently 1:1, kept
# as an explicit map so a future per-portal mapping only touches this dict).
_PROPERTY_TYPE_MAP = {
    "residential": "residential",
    "commercial": "commercial",
    "industrial": "industrial",
    "land": "land",
}


class XmlFeedController(http.Controller):

    def _image_url(self, base_url, model, record_id, field="image_1920"):
        return "%s/web/image/%s/%d/%s" % (base_url.rstrip("/"), model, record_id, field)

    def _build_property_element(self, property_rec, base_url):
        prop_el = ET.Element("property")

        ET.SubElement(prop_el, "reference_number").text = (
            property_rec.property_code or str(property_rec.id)
        )
        ET.SubElement(prop_el, "title").text = property_rec.name or ""
        # description is stored as HTML (rich-text editable in the backend); the
        # feed schema is plain text, so strip markup before it reaches portals.
        ET.SubElement(prop_el, "description").text = (
            html2plaintext(property_rec.description) if property_rec.description else ""
        )
        ET.SubElement(prop_el, "property_type").text = _PROPERTY_TYPE_MAP.get(
            property_rec.property_type, property_rec.property_type or ""
        )

        offering_el = ET.SubElement(prop_el, "offering")
        sale_lease = property_rec.sale_lease
        # sale_lease is declared as a ('sale', 'lease', 'both') Selection on
        # property.details, but live data also contains 'for_sale'/'for_tenancy'
        # (written by wizard/unit_creation.py and wizard/booking_wizard.py) —
        # a pre-existing inconsistency in the module, handled here rather than
        # silently dropping the majority of records from the feed.
        is_sale_offering = sale_lease in ("sale", "for_sale", "both")
        is_lease_offering = sale_lease in ("lease", "for_tenancy", "both")
        if is_sale_offering and property_rec.sale_price:
            ET.SubElement(offering_el, "sale_price").text = str(property_rec.sale_price)
            ET.SubElement(offering_el, "currency").text = property_rec.currency_id.name or ""
        if is_lease_offering and property_rec.rent_price:
            rent_el = ET.SubElement(offering_el, "rent")
            ET.SubElement(rent_el, "price").text = str(property_rec.rent_price)
            ET.SubElement(rent_el, "currency").text = property_rec.currency_id.name or ""
            # property.details has no listing-level rent frequency field;
            # UAE rental listings are conventionally quoted per year.
            ET.SubElement(rent_el, "frequency").text = "yearly"

        location_el = ET.SubElement(prop_el, "location")
        ET.SubElement(location_el, "address").text = property_rec.address or ""
        ET.SubElement(location_el, "city").text = property_rec.city or ""
        ET.SubElement(location_el, "region").text = property_rec.region_id.name or ""
        ET.SubElement(location_el, "state").text = property_rec.state_id.name or ""
        ET.SubElement(location_el, "country").text = property_rec.country_id.name or ""
        if property_rec.project_id:
            ET.SubElement(location_el, "project").text = property_rec.project_id.name or ""

        ET.SubElement(prop_el, "bedrooms").text = str(property_rec.bedrooms or 0)
        ET.SubElement(prop_el, "bathrooms").text = str(property_rec.bathrooms or 0)
        area_el = ET.SubElement(prop_el, "area")
        ET.SubElement(area_el, "value").text = str(property_rec.area or 0)
        ET.SubElement(area_el, "unit").text = "sqft"

        images_el = ET.SubElement(prop_el, "images")
        if property_rec.image_1920:
            ET.SubElement(images_el, "image").text = self._image_url(
                base_url, "property.details", property_rec.id
            )
        gallery = request.env["property.images"].sudo().search(
            [("property_id", "=", property_rec.id)], order="sequence, id"
        )
        for image_rec in gallery:
            if image_rec.image:
                ET.SubElement(images_el, "image").text = self._image_url(
                    base_url, "property.images", image_rec.id, field="image"
                )

        # Agent/broker contact: property.details has no dedicated broker
        # field, so the owner (falling back to landlord) is exposed as the
        # listing contact, consistent with how the module already treats
        # owner_id/landlord_id as the property's responsible partner.
        contact = property_rec.owner_id or property_rec.landlord_id
        agent_el = ET.SubElement(prop_el, "agent")
        ET.SubElement(agent_el, "name").text = contact.name or "" if contact else ""
        ET.SubElement(agent_el, "email").text = contact.email or "" if contact else ""
        ET.SubElement(agent_el, "phone").text = (contact.mobile or contact.phone or "") if contact else ""

        # Read from the RERA Trakheesi permit number; required by DLD
        # for all property listings on external portals.
        ET.SubElement(prop_el, "permit_number").text = (
            property_rec.trakheesi_permit_number or ""
        )

        ET.SubElement(prop_el, "last_updated").text = fields.Datetime.to_string(
            property_rec.write_date
        ) if property_rec.write_date else ""

        return prop_el

    def _build_feed_xml(self, portal, base_url):
        properties = request.env["property.details"].sudo().search(
            [("active", "=", True), ("state", "in", _LISTABLE_STATES)]
        )
        root = ET.Element("list")
        root.set("portal", portal.code or "")
        root.set("generated_at", fields.Datetime.to_string(fields.Datetime.now()))
        for property_rec in properties:
            root.append(self._build_property_element(property_rec, base_url))
        return ET.tostring(root, encoding="unicode")

    def _error_feed(self, message):
        root = ET.Element("feed")
        ET.SubElement(root, "status").text = "error"
        ET.SubElement(root, "message").text = message
        return ET.tostring(root, encoding="unicode")

    @http.route(['/portal-feed/<string:portal_code>'], type='http', auth='public', csrf=False)
    def portal_feed(self, portal_code, token=None, **kwargs):
        """Public XML feed endpoint with token authentication"""

        # Input validation: portal_code should be alphanumeric or underscore
        if not portal_code or not portal_code.replace('_', '').isalnum():
            _logger.warning(
                "Invalid portal code attempted: %s from IP %s",
                portal_code, request.httprequest.remote_addr
            )
            return request.make_response(
                'Invalid portal code',
                [('Content-Type', 'text/plain')],
                status=400
            )

        # Search for portal connector
        portal = request.env['portal.connector'].sudo().search(
            [('code', '=', portal_code)],
            limit=1
        )

        # Verify portal exists and token matches (constant-time compare; fail closed
        # if either side is empty so a blank stored token can never grant access)
        if (
            not portal
            or not portal.xml_feed_token
            or not token
            or not hmac.compare_digest(token, portal.xml_feed_token)
        ):
            _logger.warning(
                "Unauthorized feed access: portal=%s, token_provided=%s, ip=%s",
                portal_code,
                bool(token),
                request.httprequest.remote_addr
            )
            return request.make_response(
                'Unauthorized',
                [('Content-Type', 'text/plain')],
                status=401
            )

        # Log successful access and update usage tracking
        _logger.info(
            "Feed accessed successfully: portal=%s, ip=%s",
            portal_code,
            request.httprequest.remote_addr
        )

        # Update token usage statistics
        portal.sudo().write({
            'token_last_used': fields.Datetime.now(),
            'token_usage_count': portal.token_usage_count + 1,
        })

        base_url = request.env['ir.config_parameter'].sudo().get_param('web.base.url', default='')
        try:
            body = "<?xml version='1.0' encoding='UTF-8'?>" + self._build_feed_xml(portal, base_url)
            status = 200
        except Exception:
            _logger.exception("Feed generation failed for portal=%s", portal_code)
            body = "<?xml version='1.0' encoding='UTF-8'?>" + self._error_feed(
                "Feed generation failed"
            )
            status = 500

        return request.make_response(
            body,
            [('Content-Type', 'application/xml')],
            status=status,
        )
