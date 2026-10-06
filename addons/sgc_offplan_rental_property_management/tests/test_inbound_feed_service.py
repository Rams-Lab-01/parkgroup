# -*- coding: utf-8 -*-
"""End-to-end tests for the inbound feed ingestion pipeline.

Exercises models/portal/inbound_feed_service.py against sample XML
fixtures that mirror the generic feed schema documented at the top of
that module. The fixtures live in tests/fixtures/.

These tests intentionally do NOT use HttpCase: the controller endpoint
(inbound_feed_controller.py) is a thin wrapper around the service, so
testing the service directly is the highest-value coverage. The
controller's HTTP routing + auth flow is exercised by the smoke tests
that ship with Odoo itself.

Coverage:
- TestHappyPath: 3 properties in sample_bayut_feed.xml are created,
  currency / state / country / region / project resolve against
  pre-seeded ORM records, portal_line is linked, is_feed_sourced flips
  True on the resulting properties.
- TestUpdatePath: re-running the same feed updates rather than creates;
  created_count drops to 0 on the second run, updated_count = 3.
- TestAddNewProperty: appending a 4th <property> to the same feed after
  an initial run produces (created=1, updated=3).
- TestErrorsAreCountedNotFatal: sample_mixed_feed.xml has a malformed
  property (missing reference_number) between two valid ones; the batch
  continues and reports created=2 with 1 error.
- TestMalformedXml: feeding garbage raises ValidationError.
- TestRegionMissIsGraceful: region/project/country strings that match no
  record do NOT crash; the related fields stay unset.
- TestServiceModuleEntryPoints: all six public functions are importable
  and have the expected signatures.
"""
import os
import xml.etree.ElementTree as ET
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _read_fixture(filename):
    with open(os.path.join(FIXTURES_DIR, filename), encoding="utf-8") as fh:
        return fh.read()


@tagged("post_install", "-at_install", "inbound_feed")
class TestServiceModuleEntryPoints(TransactionCase):
    """Sanity check: the public API is importable + has the right shape."""

    def test_all_public_functions_exist(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        for name in (
            "fetch_feed_xml",
            "process_feed_properties",
            "parse_feed_property",
            "resolve_related_records",
            "prepare_property_update_vals",
            "create_property_from_vals",
            "download_and_attach_images",
        ):
            self.assertTrue(
                hasattr(inbound_feed_service, name),
                "inbound_feed_service.{} is missing".format(name),
            )
            self.assertTrue(
                callable(getattr(inbound_feed_service, name)),
                "inbound_feed_service.{} is not callable".format(name),
            )


@tagged("post_install", "-at_install", "inbound_feed")
class TestHappyPath(TransactionCase):
    """Parse the 3-property Bayut-shaped feed, assert full pipeline."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env["res.partner"].create({"name": "Test Owner"})
        # Country: UAE
        cls.country_uae = cls.env["res.country"].search([
            ("name", "=", "United Arab Emirates"),
        ], limit=1) or cls.env["res.country"].create({
            "name": "United Arab Emirates",
            "code": "AE",
        })
        # States (res.country.state): Dubai, Abu Dhabi, Sharjah
        for state_name in ("Dubai", "Abu Dhabi", "Sharjah"):
            existing = cls.env["res.country.state"].search([
                ("name", "=", state_name),
                ("country_id", "=", cls.country_uae.id),
            ], limit=1)
            if not existing:
                cls.env["res.country.state"].create({
                    "name": state_name,
                    "country_id": cls.country_uae.id,
                })
        for region_name in ("Dubai Marina", "Palm Jumeirah"):
            existing = cls.env["property.region"].search([
                ("name", "=", region_name),
            ], limit=1)
            if not existing:
                cls.env["property.region"].create({"name": region_name})
        for project_name in ("Marina Heights Tower", "Palm Jumeirah"):
            existing = cls.env["property.project"].search([
                ("name", "=", project_name),
            ], limit=1)
            if not existing:
                cls.env["property.project"].create({
                    "name": project_name,
                })
        # Currency AED — Odoo's base currency data includes it but inactive
        # by default, so the search must bypass the active_test to find it;
        # otherwise create() collides with the existing (inactive) row on
        # the name unique constraint instead of reactivating it.
        cls.currency_aed = cls.env["res.currency"].with_context(
            active_test=False).search([("name", "=", "AED")], limit=1)
        if cls.currency_aed:
            if not cls.currency_aed.active:
                cls.currency_aed.active = True
        else:
            cls.currency_aed = cls.env["res.currency"].create({
                "name": "AED",
                "symbol": "AED",
                "rounding": 0.01,
                "active": True,
            })
        # Portal connector for "bayut". A production-mirror scratch already
        # carries one (unique per (code, company_id)), so reuse and reactivate
        # it instead of colliding - same pattern as the AED currency above.
        cls.portal = cls.env["portal.connector"].with_context(
            active_test=False).search([
                ("code", "=", "bayut"),
                ("company_id", "=", cls.env.company.id),
            ], limit=1)
        if cls.portal:
            if not cls.portal.active:
                cls.portal.active = True
        else:
            cls.portal = cls.env["portal.connector"].create({
                "name": "Bayut Test",
                "code": "bayut",
                "company_id": cls.env.company.id,
                "active": True,
            })

    def test_feed_creates_three_properties(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = _read_fixture("sample_bayut_feed.xml")

        before_ids = set(self.env["property.portal.line"].search([
            ("portal_id", "=", self.portal.id),
        ]).ids)

        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            created, updated, errors = inbound_feed_service.process_feed_properties(
                self.env, self.portal, feed_xml,
            )

        self.assertEqual(created, 3, "expected 3 created, got {}".format(created))
        self.assertEqual(updated, 0)
        self.assertEqual(errors, [], "unexpected errors: {}".format(errors))

        # A production-mirror scratch already carries this connector's lines, so
        # count only what this run produced (created == 3 above is the
        # create-count assertion) - same tolerance as the AED currency above.
        portal_lines = self.env["property.portal.line"].search([
            ("portal_id", "=", self.portal.id),
        ]).filtered(lambda line: line.id not in before_ids)
        self.assertEqual(len(portal_lines), 3)

        properties = self.env["property.details"].search([
            ("id", "in", portal_lines.property_id.ids),
        ])
        for prop in properties:
            self.assertTrue(prop.active)
            self.assertTrue(prop.name)
            self.assertEqual(prop.portal_line_count, 1)
            self.assertTrue(
                prop.is_feed_sourced,
                "property {} should be marked feed-sourced".format(prop.id),
            )
            self.assertIn("Bayut", prop.feed_source_label)

    def test_currency_resolves_to_aed(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = _read_fixture("sample_bayut_feed.xml")

        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            inbound_feed_service.process_feed_properties(
                self.env, self.portal, feed_xml,
            )

        portal_lines = self.env["property.portal.line"].search([
            ("portal_id", "=", self.portal.id),
            ("external_id", "=", "BAY-MHT-1204"),
        ], limit=1)
        prop = portal_lines.property_id
        self.assertTrue(prop, "BAY-MHT-1204 not imported")
        self.assertEqual(
            prop.currency_id.id, self.currency_aed.id,
            "currency_id did not resolve to AED",
        )

    def test_state_resolves_to_dubai(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = _read_fixture("sample_bayut_feed.xml")

        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            inbound_feed_service.process_feed_properties(
                self.env, self.portal, feed_xml,
            )

        portal_lines = self.env["property.portal.line"].search([
            ("portal_id", "=", self.portal.id),
            ("external_id", "=", "BAY-MHT-1204"),
        ], limit=1)
        prop = portal_lines.property_id
        self.assertTrue(prop.state_id, "state_id did not resolve")
        self.assertEqual(prop.state_id.name, "Dubai")

    def test_project_resolves_for_marina_heights(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = _read_fixture("sample_bayut_feed.xml")

        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            inbound_feed_service.process_feed_properties(
                self.env, self.portal, feed_xml,
            )

        portal_lines = self.env["property.portal.line"].search([
            ("portal_id", "=", self.portal.id),
            ("external_id", "=", "BAY-MHT-1204"),
        ], limit=1)
        prop = portal_lines.property_id
        self.assertTrue(prop.project_id, "project_id did not resolve")
        self.assertEqual(prop.project_id.name, "Marina Heights Tower")

    def test_sale_lease_field_set_correctly(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = _read_fixture("sample_bayut_feed.xml")

        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            inbound_feed_service.process_feed_properties(
                self.env, self.portal, feed_xml,
            )

        def _prop_by_ref(ref):
            line = self.env["property.portal.line"].search([
                ("portal_id", "=", self.portal.id),
                ("external_id", "=", ref),
            ], limit=1)
            return line.property_id

        # Property 1: both sale_price and rent_price → 'both'
        self.assertEqual(_prop_by_ref("BAY-MHT-1204").sale_lease, "both")
        # Property 2: only sale_price → 'sale'
        self.assertEqual(_prop_by_ref("BAY-PJV-FROND-G-07").sale_lease, "sale")
        # Property 3: only rent_price → 'lease'
        self.assertEqual(_prop_by_ref("BAY-SHJ-STUDIO-04").sale_lease, "lease")

    def test_trakheesi_permit_persisted(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = _read_fixture("sample_bayut_feed.xml")

        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            inbound_feed_service.process_feed_properties(
                self.env, self.portal, feed_xml,
            )

        def _prop_by_ref(ref):
            line = self.env["property.portal.line"].search([
                ("portal_id", "=", self.portal.id),
                ("external_id", "=", ref),
            ], limit=1)
            return line.property_id

        self.assertEqual(
            _prop_by_ref("BAY-MHT-1204").trakheesi_permit_number,
            "TRK-2026-001234",
        )
        # Property 3 had no permit in the feed → empty string is acceptable.
        self.assertFalse(_prop_by_ref("BAY-SHJ-STUDIO-04").trakheesi_permit_number)


@tagged("post_install", "-at_install", "inbound_feed")
class TestUpdatePath(TransactionCase):
    """Re-running the same feed updates existing properties."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = cls.env["portal.connector"].create({
            "name": "Property Finder Test",
            "code": "property_finder",
            "company_id": cls.env.company.id,
        })

    def test_rerun_updates_not_creates(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = _read_fixture("sample_bayut_feed.xml")

        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            created1, updated1, errs1 = (
                inbound_feed_service.process_feed_properties(
                    self.env, self.portal, feed_xml,
                )
            )
            self.assertEqual(created1, 3)
            self.assertEqual(updated1, 0)
            self.assertEqual(errs1, [])

            created2, updated2, errs2 = (
                inbound_feed_service.process_feed_properties(
                    self.env, self.portal, feed_xml,
                )
            )
            self.assertEqual(created2, 0, "rerun must not re-create")
            self.assertEqual(updated2, 3, "rerun must update all 3")
            self.assertEqual(errs2, [])

    def test_appending_new_property_yields_mixed_counts(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        original_xml = _read_fixture("sample_bayut_feed.xml")
        augmented_xml = original_xml.replace(
            "</list>",
            "<property><reference_number>BAY-NEW-999</reference_number>"
            "<title>Brand New Listing</title>"
            "<property_type>residential</property_type>"
            "<offering><sale_price>750000</sale_price>"
            "<currency>AED</currency></offering>"
            "<location><city>Dubai</city><region>Dubai</region>"
            "<country>United Arab Emirates</country></location>"
            "<bedrooms>1</bedrooms><bathrooms>1</bathrooms></property>"
            "</list>",
        )

        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            inbound_feed_service.process_feed_properties(
                self.env, self.portal, original_xml,
            )
            created, updated, errs = inbound_feed_service.process_feed_properties(
                self.env, self.portal, augmented_xml,
            )
            self.assertEqual(created, 1, "expected 1 new")
            self.assertEqual(updated, 3, "expected 3 updates of prior batch")
            self.assertEqual(errs, [])


@tagged("post_install", "-at_install", "inbound_feed")
class TestErrorsAreCountedNotFatal(TransactionCase):
    """A malformed property in the middle of a feed must not abort the batch."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = cls.env["portal.connector"].create({
            "name": "Dubizzle Test",
            "code": "dubizzle",
            "company_id": cls.env.company.id,
        })

    def test_mixed_feed_continues_past_error(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = _read_fixture("sample_mixed_feed.xml")

        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            created, updated, errors = inbound_feed_service.process_feed_properties(
                self.env, self.portal, feed_xml,
            )

        self.assertEqual(created, 2, "expected 2 valid properties created")
        self.assertEqual(updated, 0)
        self.assertEqual(len(errors), 1, "expected 1 error for malformed entry")
        self.assertIn("reference_number", errors[0])


@tagged("post_install", "-at_install", "inbound_feed")
class TestMalformedXml(TransactionCase):

    def test_garbage_xml_raises_validation_error(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        portal = self.env["portal.connector"].create({
            "name": "Test",
            "code": "custom",
            "company_id": self.env.company.id,
        })
        with self.assertRaises(ValidationError):
            inbound_feed_service.process_feed_properties(
                self.env, portal, "<not-xml-at-all><<>>><",
            )


@tagged("post_install", "-at_install", "inbound_feed")
class TestRegionMissIsGraceful(TransactionCase):
    """Unmatched region/country/project text does NOT raise."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = cls.env["portal.connector"].create({
            "name": "Custom Portal Test",
            "code": "custom",
            "company_id": cls.env.company.id,
        })

    def test_unknown_region_does_not_crash(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
<list>
    <property>
        <reference_number>UNKNOWN-001</reference_number>
        <title>Mars Colony Habitat</title>
        <property_type>residential</property_type>
        <offering>
            <sale_price>999999</sale_price>
            <currency>XXX</currency>
        </offering>
        <location>
            <city>Olympus Mons</city>
            <region>Tharsis</region>
            <country>Mars</country>
            <project>Future Colony</project>
        </location>
        <bedrooms>3</bedrooms>
        <bathrooms>2</bathrooms>
    </property>
</list>"""
        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            created, updated, errors = inbound_feed_service.process_feed_properties(
                self.env, self.portal, feed_xml,
            )
        self.assertEqual(created, 1, "creation must succeed despite no matches")
        self.assertEqual(errors, [])

        line = self.env["property.portal.line"].search([
            ("portal_id", "=", self.portal.id),
            ("external_id", "=", "UNKNOWN-001"),
        ], limit=1)
        prop = line.property_id
        # Related fields must remain unset, NOT raise.
        self.assertFalse(prop.state_id)
        self.assertFalse(prop.country_id)
        self.assertFalse(prop.region_id)
        self.assertFalse(prop.project_id)
        self.assertFalse(prop.currency_id)


@tagged("post_install", "-at_install", "inbound_feed")
class TestParseFeedPropertyDirect(TransactionCase):
    """Unit-test parse_feed_property against a single XML node."""

    def test_required_fields_missing_raises_value_error(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        root = ET.fromstring(
            "<list><property><title>No reference</title></property></list>"
        )
        prop_elem = root.find("property")
        with self.assertRaises(ValueError):
            inbound_feed_service.parse_feed_property(self.env, prop_elem)

    def test_get_text_handles_missing_tag_and_empty_text(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        self.assertIsNone(inbound_feed_service._get_text(None, "x"))
        self.assertIsNone(
            inbound_feed_service._get_text(
                ET.fromstring("<root><empty></empty></root>"), "missing",
            )
        )
        self.assertEqual(
            inbound_feed_service._get_text(
                ET.fromstring("<root><x>  hello  </x></root>"), "x",
            ),
            "hello",
        )

    def test_get_integer_handles_float_string(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        self.assertEqual(
            inbound_feed_service._get_integer(
                ET.fromstring("<root><x>3.0</x></root>"), "x",
            ),
            3,
        )
        self.assertIsNone(
            inbound_feed_service._get_integer(
                ET.fromstring("<root><x>not-a-number</x></root>"), "x",
            )
        )

    def test_parse_datetime_accepts_iso_and_falls_back(self):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        # ISO with TZ — fields.Datetime.from_string may accept it
        iso = inbound_feed_service._parse_datetime("2026-08-15T10:30:00")
        self.assertIsNotNone(iso)
        # Plain date
        self.assertIsNotNone(inbound_feed_service._parse_datetime("2026-08-15"))
        # Garbage
        self.assertIsNone(inbound_feed_service._parse_datetime("not-a-date"))