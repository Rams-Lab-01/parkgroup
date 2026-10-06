# -*- coding: utf-8 -*-
#
# Inbound Feed Service — shared XML-fetch + parsing + record-creation logic.
# ------------------------------------------------------------------
# This module exists so that BOTH the HTTP controller endpoint
# (/portal-feed-ingest/<portal_code>) AND the scheduled cron job
# (process_inbound_feeds on portal.connector) call the same code.
#
# Calling convention: every public function takes an `env` parameter as
# its first argument, so the caller (controller or cron) decides which
# ORM environment is used. Controller passes request.env, cron passes
# self.env (with sudo() applied by the model method).
#
# CREDENTIAL GAP (intentional, not a bug): there is no live partner
# agreement with Bayut/Dubizzle yet, so no real feed specification is
# available. The schema below is a reasonable, generic assumption based
# on the property fields these portals commonly expose in their XML feeds.
# Once real feed specs are available, only parse_feed_property() needs to
# change to match the real field names/structure.
#
# ASSUMED FEED XML SCHEMA (property element):
# <property>
#     <reference_number>string — unique ID from portal</reference_number>
#     <title>string — property name/title</title>
#     <description>string — property description (HTML or plain text)</description>
#     <property_type>string — residential/commercial/industrial/land</property_type>
#     <offering>
#         <sale_price>decimal — price for sale (if for sale)</sale_price>
#         <rent_price>decimal — price for rent (if for rent)</rent_price>
#         <currency>string — currency code (e.g., AED, USD)</currency>
#         <frequency>string — rent frequency (monthly/yearly)</frequency>
#     </offering>
#     <location>
#         <address>string — full address</address>
#         <city>string — city</city>
#         <region>string — region/emirate</region>
#         <country>string — country</country>
#         <project>string — project/development name</project>
#     </location>
#     <bedrooms>integer — number of bedrooms</bedrooms>
#     <bathrooms>integer — number of bathrooms</bathrooms>
#     <area>
#         <value>decimal — area size</value>
#         <unit>string — unit (sqft, sqm, etc.)</unit>
#     </area>
#     <images>
#         <image>string — URL to image</image>
#         <!-- Multiple image elements possible -->
#     </images>
#     <agent>
#         <name>string — agent/broker name</name>
#         <email>string — agent email</email>
#         <phone>string — agent phone</phone>
#     </agent>
#     <permit_number>string — Trakheesi/RERA permit number</permit_number>
#     <last_updated>datetime — when property was last updated</last_updated>
# </property>
#
# The feed root element is expected to be <list> or <properties> containing
# multiple <property> elements.
import base64
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from odoo import fields
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# property.details.property_type -> feed vocabulary (currently 1:1, kept
# as an explicit map so a future per-portal mapping only touches this dict).
_PROPERTY_TYPE_MAP = {
    "residential": "residential",
    "commercial": "commercial",
    "industrial": "industrial",
    "land": "land",
}

# Cap on per-property image downloads — protects the cron from runaway
# memory if a feed contains dozens of large URLs.
_MAX_IMAGES_PER_PROPERTY = 5
# HTTP timeout (seconds) for feed XML and image downloads.
_FEED_HTTP_TIMEOUT = 30
_IMAGE_HTTP_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def fetch_feed_xml(env, feed_url, username=None, password=None):
    """Fetch XML feed from URL with optional basic auth.

    Raises ValidationError on any HTTP/URL failure so callers can surface
    a clear error to the user / sync log without leaking raw stack traces.
    """
    try:
        req = Request(feed_url)
        if username and password:
            credentials = base64.b64encode(
                "{}:{}".format(username, password).encode()
            ).decode()
            req.add_header("Authorization", "Basic {}".format(credentials))
        req.add_header("User-Agent", "Odoo Property Management Feed Parser")
        with urlopen(req, timeout=_FEED_HTTP_TIMEOUT) as response:
            return response.read().decode("utf-8")
    except HTTPError as e:
        _logger.error("HTTP error fetching feed from %s: %s", feed_url, e.code)
        raise ValidationError("HTTP {}: {}".format(e.code, e.reason))
    except URLError as e:
        _logger.error("URL error fetching feed from %s: %s", feed_url, e.reason)
        raise ValidationError("Failed to fetch feed: {}".format(e.reason))
    except Exception as e:
        _logger.error("Unexpected error fetching feed from %s: %s", feed_url, e)
        raise ValidationError("Feed fetch failed: {}".format(e))


def process_feed_properties(env, portal, feed_xml):
    """Process all properties in the feed XML for the given portal.

    Returns (created_count, updated_count, errors_list).
    Updates portal_line records in place to track last_sync / last_error.
    """
    try:
        root = ET.fromstring(feed_xml)
    except ET.ParseError as e:
        _logger.error("Failed to parse XML feed from portal %s: %s",
                      portal.code, e)
        raise ValidationError("Invalid XML feed: {}".format(e))

    property_elements = _extract_property_elements(root)
    if not property_elements:
        _logger.warning("No property elements found in feed from portal %s",
                        portal.code)
        return 0, 0, []

    created_count = 0
    updated_count = 0
    errors = []
    portal_line_env = env["property.portal.line"].sudo()

    for prop_elem in property_elements:
        try:
            prop_vals = parse_feed_property(env, prop_elem)
            resolve_related_records(env, prop_vals)

            portal_line = portal_line_env.search([
                ("portal_id", "=", portal.id),
                ("external_id", "=", prop_vals["reference_number"]),
            ], limit=1)

            if portal_line and portal_line.property_id:
                update_vals = prepare_property_update_vals(env, prop_vals)
                portal_line.property_id.sudo().write(update_vals)
                portal_line.sudo().write({
                    "last_sync": fields.Datetime.now(),
                    "last_error": False,
                    "status": "published",
                })
                updated_count += 1
            elif portal_line and not portal_line.property_id:
                errors.append(
                    "Portal line exists but property record missing for "
                    "reference {}".format(prop_vals["reference_number"])
                )
            else:
                property_rec = create_property_from_vals(env, prop_vals)
                if property_rec:
                    portal_line_env.create({
                        "property_id": property_rec.id,
                        "portal_id": portal.id,
                        "external_id": prop_vals["reference_number"],
                        "last_sync": fields.Datetime.now(),
                        "last_error": False,
                        "status": "published",
                    })
                    created_count += 1
                else:
                    errors.append(
                        "Failed to create property for reference {}".format(
                            prop_vals["reference_number"]
                        )
                    )
        except Exception as e:  # noqa: BLE001
            _logger.error(
                "Error processing property from feed (portal %s): %s",
                portal.code, e,
            )
            errors.append("Property processing error: {}".format(e))
            continue

    return created_count, updated_count, errors


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

def _extract_property_elements(root):
    """Locate <property> elements regardless of root tag / namespace prefix."""
    property_elements = root.findall(".//property")
    if not property_elements:
        property_elements = root.findall("property")
    return property_elements


def parse_feed_property(env, property_element):
    """Parse a single property XML element into a dictionary of values.

    Raises ValueError on malformed/missing required data.

    Text-only values (currency, region, country, project) are returned as
    *_text keys so resolve_related_records() can look up the corresponding
    ORM record ids and add the *_<id>_id keys.
    """
    if property_element is None or not property_element.tag.endswith("property"):
        raise ValueError("Invalid property element")

    prop_elem = property_element

    reference_number = _get_text(prop_elem, "reference_number")
    if not reference_number:
        raise ValueError("Missing or empty reference_number")

    title = _get_text(prop_elem, "title")
    if not title:
        raise ValueError("Missing or empty title")

    description = _get_text(prop_elem, "description")
    property_type_text = _get_text(prop_elem, "property_type")

    # Offering block — both prices + currency text (currency_id resolved later).
    sale_price = None
    rent_price = None
    currency_text = None
    offering_elem = prop_elem.find("offering")
    if offering_elem is not None:
        sale_price = _get_decimal(offering_elem, "sale_price")
        rent_price = _get_decimal(offering_elem, "rent_price")
        currency_text = _get_text(offering_elem, "currency")

    # Location block — keep text values for resolution against ORM records.
    address = None
    city = None
    region_text = None
    country_text = None
    project_text = None
    location_elem = prop_elem.find("location")
    if location_elem is not None:
        address = _get_text(location_elem, "address")
        city = _get_text(location_elem, "city")
        region_text = _get_text(location_elem, "region")
        country_text = _get_text(location_elem, "country")
        project_text = _get_text(location_elem, "project")

    bedrooms = _get_integer(prop_elem, "bedrooms")
    bathrooms = _get_integer(prop_elem, "bathrooms")

    area = None
    area_elem = prop_elem.find("area")
    if area_elem is not None:
        area_value = _get_decimal(area_elem, "value")
        # No conversion logic — feed is assumed to be sqft for now.
        if area_value is not None:
            area = area_value

    image_urls = []
    images_elem = prop_elem.find("images")
    if images_elem is not None:
        for image_elem in images_elem.findall("image"):
            image_url = _get_text(image_elem, None)
            if image_url:
                image_urls.append(image_url)

    agent_name = None
    agent_email = None
    agent_phone = None
    agent_elem = prop_elem.find("agent")
    if agent_elem is not None:
        agent_name = _get_text(agent_elem, "name")
        agent_email = _get_text(agent_elem, "email")
        agent_phone = _get_text(agent_elem, "phone")

    permit_number = _get_text(prop_elem, "permit_number")

    last_updated = _parse_datetime(_get_text(prop_elem, "last_updated"))

    property_type = None
    if property_type_text:
        property_type = _PROPERTY_TYPE_MAP.get(
            property_type_text.lower(), property_type_text.lower()
        )
        if property_type not in ("residential", "commercial", "industrial", "land"):
            property_type = "residential"

    if sale_price is not None and rent_price is not None:
        sale_lease = "both"
    elif sale_price is not None:
        sale_lease = "sale"
    elif rent_price is not None:
        sale_lease = "lease"
    else:
        sale_lease = None

    return {
        "reference_number": reference_number,
        "name": title,
        "description": description,
        "property_type": property_type,
        "sale_price": sale_price,
        "rent_price": rent_price,
        "currency_text": currency_text,
        "address": address,
        "city": city,
        "region_text": region_text,
        "country_text": country_text,
        "project_text": project_text,
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "area": area,
        "image_urls": image_urls,
        "agent_name": agent_name,
        "agent_email": agent_email,
        "agent_phone": agent_phone,
        "trakheesi_permit_number": permit_number,
        "last_updated": last_updated,
        "sale_lease": sale_lease,
    }


def _get_text(element, tag):
    """Safely read text content of a child element. tag=None returns own text."""
    if element is None:
        return None
    if tag is None:
        text = element.text
    else:
        found = element.find(tag)
        if found is None:
            return None
        text = found.text
    if not text:
        return None
    stripped = text.strip()
    return stripped or None


def _get_decimal(element, tag):
    text = _get_text(element, tag)
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _get_integer(element, tag):
    text = _get_text(element, tag)
    if text is None:
        return None
    try:
        return int(float(text))  # Handle cases like "3.0"
    except ValueError:
        return None


def _parse_datetime(text):
    if not text:
        return None
    try:
        return fields.Datetime.from_string(text)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# ORM resolution + property creation
# ---------------------------------------------------------------------------

def resolve_related_records(env, vals):
    """Resolve text identifiers into ORM record ids on `vals` in place.

    Reads `currency_text`, `region_text`, `country_text`, `project_text`
    keys (set by parse_feed_property) and adds the corresponding *_id keys
    to vals when a match is found.

    `region_text` is matched against BOTH property.region (sub-region
    groupings) and res.country.state (UAE emirates) — whichever has a
    match wins; state_id is preferred when both match because that's the
    field Odoo uses for UAE emirate-level reporting.
    """
    currency_text = vals.pop("currency_text", None)
    if currency_text:
        currency_rec = env["res.currency"].sudo().search([
            ("name", "=ilike", currency_text),
            ("active", "=", True),
        ], limit=1)
        # currency_id has a create-time default (company currency); an
        # unresolved-but-given currency code must override that default to
        # False rather than silently inherit it, the same as the other
        # unmatched location fields below.
        vals["currency_id"] = currency_rec.id if currency_rec else False
        if not currency_rec:
            # PROP-D7: silent substitution of the company currency for an
            # unrecognized feed currency code would misrepresent price data
            # financially. currency_id is left unset (see above); this log
            # is the review signal an operator needs to catch and correct
            # the source feed's currency code.
            _logger.warning(
                "Unrecognized currency code %r on feed property %s -- "
                "currency_id left unset instead of defaulting.",
                currency_text, vals.get("reference_number"),
            )

    country_text = vals.pop("country_text", None)
    if country_text:
        country_rec = env["res.country"].sudo().search([
            ("name", "=ilike", country_text),
        ], limit=1)
        if country_rec:
            vals["country_id"] = country_rec.id

    region_text = vals.pop("region_text", None)
    if region_text:
        # Prefer res.country.state (UAE emirates) over property.region.
        state_rec = env["res.country.state"].sudo().search([
            ("name", "=ilike", region_text),
            "|",
            ("country_id.name", "=ilike", "United Arab Emirates"),
            ("country_id.name", "=ilike", "UAE"),
        ], limit=1)
        if state_rec:
            vals["state_id"] = state_rec.id
        region_rec = env["property.region"].sudo().search([
            ("name", "=ilike", region_text),
        ], limit=1)
        if region_rec:
            vals["region_id"] = region_rec.id

    project_text = vals.pop("project_text", None)
    if project_text:
        project_rec = env["property.project"].sudo().search([
            ("name", "=ilike", project_text),
        ], limit=1)
        if project_rec:
            vals["project_id"] = project_rec.id

    return vals


def prepare_property_update_vals(env, vals):
    """Filter parsed vals down to writeable property.details fields."""
    writable = (
        "name", "description", "property_type", "sale_price", "rent_price",
        "currency_id", "area", "bedrooms", "bathrooms", "address", "city",
        "state_id", "country_id", "region_id", "project_id",
        "trakheesi_permit_number", "sale_lease",
    )
    return {k: v for k, v in vals.items() if k in writable and v is not None}


def create_property_from_vals(env, vals):
    """Create a new property.details record from parsed feed values."""
    writable = (
        "name", "description", "property_type", "sale_price", "rent_price",
        "currency_id", "area", "bedrooms", "bathrooms", "address", "city",
        "state_id", "country_id", "region_id", "project_id",
        "trakheesi_permit_number", "sale_lease",
    )
    prop_vals = {k: vals[k] for k in writable if vals.get(k) is not None}
    if not prop_vals.get("name"):
        # Name is required by property.details; bail out cleanly if missing.
        _logger.error("Refusing to create property without a name: %s", vals)
        return False
    try:
        property_rec = env["property.details"].sudo().create(prop_vals)
    except Exception as e:  # noqa: BLE001
        _logger.error("Error creating property from feed values: %s", e)
        return False

    image_urls = vals.get("image_urls") or []
    if image_urls:
        download_and_attach_images(env, property_rec, image_urls)
    return property_rec


def download_and_attach_images(env, property_rec, image_urls):
    """Download images from URLs and attach first one as main, rest as gallery."""
    try:
        for i, image_url in enumerate(image_urls[:_MAX_IMAGES_PER_PROPERTY]):
            try:
                req = Request(image_url, headers={
                    "User-Agent": "Odoo Property Management",
                })
                with urlopen(req, timeout=_IMAGE_HTTP_TIMEOUT) as response:
                    image_data = response.read()

                is_main = (i == 0)
                if is_main and not property_rec.image_1920:
                    property_rec.sudo().write({
                        "image_1920": base64.b64encode(image_data).decode(
                            "utf-8"
                        ),
                    })
                else:
                    env["property.images"].sudo().create({
                        "property_id": property_rec.id,
                        "name": "Feed Image {}".format(i + 1),
                        "image": base64.b64encode(image_data).decode(
                            "utf-8"
                        ),
                        "sequence": i + 1,
                    })
            except Exception as e:  # noqa: BLE001
                _logger.warning(
                    "Failed to download/process image %s: %s", image_url, e
                )
                continue
    except Exception as e:  # noqa: BLE001
        _logger.error(
            "Error in image download/attachment process: %s", e
        )