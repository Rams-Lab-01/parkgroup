# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestRealEstateDashboard(TransactionCase):
    """Guards the dashboard data feed and every drill-down."""

    def test_data_shape(self):
        data = self.env["sgc.realestate.dashboard"].get_dashboard_data()
        for key in ("units", "contracts", "money", "escrow",
                    "funnel", "aging", "projects", "sources"):
            self.assertIn(key, data, "dashboard payload missing '%s'" % key)
        for key in ("total", "available", "booked", "sold", "eoi"):
            self.assertIn(key, data["units"])
        for key in ("sales_value", "collected", "outstanding", "collection_rate"):
            self.assertIn(key, data["money"])

    def test_drilldowns(self):
        Dashboard = self.env["sgc.realestate.dashboard"]
        for kind in ("units", "contracts", "collected", "outstanding",
                     "escrow", "leads", "opportunities", "contracts_signed"):
            act = Dashboard.open_records(kind, {})
            self.assertEqual(act["type"], "ir.actions.act_window")
            self.assertTrue(act["res_model"])
        with self.assertRaises(Exception):
            Dashboard.open_records("does_not_exist", {})
