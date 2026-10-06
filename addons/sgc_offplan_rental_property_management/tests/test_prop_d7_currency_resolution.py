# SPDX-License-Identifier: OPL-1
"""PROP-D7 (P2 data-integrity) -- inbound feed currency resolution must
never silently substitute the company currency for a currency the feed
did not (or could not) specify correctly.

Business rule, confirmed 2026-09-05: property.details.currency_id has a
create-time default (the current company's currency). That default is
appropriate when a feed genuinely supplies no currency information at
all, but is financially misleading when a feed DID supply a currency
code and it simply failed to resolve (e.g. a stale/unsupported ISO code,
a typo, or a placeholder like "XXX") -- silently relabeling that price
as the company's currency would misstate the listing's actual value.

Three distinct outcomes are covered, matching resolve_related_records()
in models/portal/inbound_feed_service.py:
  1. Recognized currency code -> currency_id resolves to that currency.
  2. No currency code in the feed at all -> currency_id is left to the
     model's own default (company currency) -- no signal was given, so
     there is nothing to contradict.
  3. An unrecognized/unresolvable currency code -> currency_id is
     explicitly left unset (False), NOT defaulted, and a warning is
     logged as the operator-facing review signal.

Agent-created verification tests, added alongside the PROP-D7 fix
(commit 66c5862) as its regression test.
"""
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "prop_d7")
class TestPropD7CurrencyResolution(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.portal = cls.env["portal.connector"].create({
            "name": "PROP-D7 Portal Test",
            "code": "custom",
            "company_id": cls.env.company.id,
        })
        cls.currency_aed = cls.env["res.currency"].with_context(
            active_test=False).search([("name", "=", "AED")], limit=1)
        if cls.currency_aed and not cls.currency_aed.active:
            cls.currency_aed.active = True
        if not cls.currency_aed:
            cls.currency_aed = cls.env["res.currency"].create({
                "name": "AED", "symbol": "AED", "rounding": 0.01, "active": True,
            })

    def _run_feed(self, reference_number, currency_tag):
        from odoo.addons.sgc_offplan_rental_property_management.models.portal import (
            inbound_feed_service,
        )
        feed_xml = """<?xml version="1.0" encoding="UTF-8"?>
<list>
    <property>
        <reference_number>{ref}</reference_number>
        <title>PROP-D7 Test Property {ref}</title>
        <property_type>residential</property_type>
        <offering>
            <sale_price>500000</sale_price>
            {currency_tag}
        </offering>
        <location>
            <city>Test City</city>
        </location>
        <bedrooms>2</bedrooms>
        <bathrooms>1</bathrooms>
    </property>
</list>""".format(ref=reference_number, currency_tag=currency_tag)
        with patch.object(
            inbound_feed_service,
            "download_and_attach_images",
            lambda env, prop, urls: None,
        ):
            created, updated, errors = inbound_feed_service.process_feed_properties(
                self.env, self.portal, feed_xml,
            )
        self.assertEqual(created, 1)
        self.assertEqual(errors, [])
        line = self.env["property.portal.line"].search([
            ("portal_id", "=", self.portal.id),
            ("external_id", "=", reference_number),
        ], limit=1)
        return line.property_id

    # 1. Recognized currency code -> resolves correctly.
    def test_recognized_currency_code_resolves(self):
        prop = self._run_feed("PROPD7-RECOGNIZED", "<currency>AED</currency>")
        self.assertEqual(
            prop.currency_id, self.currency_aed,
            "A recognized currency code must resolve to that currency.",
        )

    # 2. No currency code supplied at all -> falls back to the model's own
    #    default (company currency). This is documented, expected
    #    behavior -- distinct from an unresolved code, which must NOT
    #    default (see test 3).
    def test_missing_currency_code_defaults_to_company_currency(self):
        prop = self._run_feed("PROPD7-MISSING", "")
        self.assertEqual(
            prop.currency_id, self.env.company.currency_id,
            "No currency in the feed at all is expected to fall back to "
            "the company's default currency (no contradicting signal was "
            "given), unlike an explicitly unresolved code.",
        )

    # 3. Unrecognized/unresolvable currency code -> explicitly unset, NOT
    #    silently defaulted to the company currency.
    def test_unrecognized_currency_code_left_unset(self):
        prop = self._run_feed("PROPD7-UNRECOGNIZED", "<currency>XXX</currency>")
        self.assertFalse(
            prop.currency_id,
            "An unrecognized currency code must leave currency_id unset, "
            "not silently substitute the company currency -- doing so "
            "would misstate the listing's actual price currency.",
        )
