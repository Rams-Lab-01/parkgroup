# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestLeadJourney(TransactionCase):
    """Guards the CRM lead <-> property sale instrument spine."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Lead = cls.env["crm.lead"]
        cls.Contract = cls.env["sale.contract"]
        cls.partner = cls.env["res.partner"].create(
            {"name": "Journey Test Buyer"})
        cls.unit = cls.env["property.details"].search(
            [("state", "=", "available")], limit=1)

    def _make_contract(self, lead, state):
        return self.Contract.create({
            "property_id": self.unit.id,
            "buyer_id": self.partner.id,
            "lead_id": lead.id,
            "sale_price": 100000.0,
            "state": state,
        })

    def test_stage_handoff_eoi_to_spa(self):
        if not self.unit:
            self.skipTest("No available property.details to test against.")
        lead = self.Lead.create(
            {"name": "Journey Lead", "property_id": self.unit.id})
        contract = self._make_contract(lead, "eoi")
        self.assertEqual(lead.contract_count, 1)
        self.assertEqual(lead.eoi_count, 1)
        proposition = self.Lead._journey_stage(
            "Proposition", "Proposal", "Qualified")
        if proposition:
            self.assertEqual(lead.stage_id, proposition)
        contract.write({"state": "spa_signed"})
        won = self.Lead._journey_stage("Won")
        if won:
            self.assertEqual(lead.stage_id, won)
        self.assertEqual(lead.probability, 100)

    def test_refund_reopens_lead(self):
        if not self.unit:
            self.skipTest("No available property.details to test against.")
        lead = self.Lead.create(
            {"name": "Journey Lead 2", "property_id": self.unit.id})
        contract = self._make_contract(lead, "booked")
        contract.write({"state": "refunded"})
        won = self.Lead._journey_stage("Won")
        self.assertNotEqual(lead.stage_id, won)

    def test_website_inquiry_links_property_and_lead(self):
        if not self.unit:
            self.skipTest("No available property.details to test against.")
        inquiry = self.env["property.website.inquiry"].create({
            "property_id": self.unit.id,
            "name": "Web Visitor",
            "email": "visitor@example.com",
        })
        self.assertTrue(inquiry.lead_id)
        self.assertEqual(inquiry.lead_id.property_id, self.unit)
