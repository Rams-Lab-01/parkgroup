# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCrmMarketingDashboard(TransactionCase):

    def test_data_shape(self):
        data = self.env["sgc.crm.marketing.dashboard"].get_dashboard_data("month")
        for key in ("pipeline", "by_stage", "by_source", "by_owner",
                    "aging", "trend", "buyers", "campaigns", "roi"):
            self.assertIn(key, data, "payload missing '%s'" % key)
        for key in ("open", "pipeline_value", "weighted_value", "win_rate",
                    "new_leads", "new_won"):
            self.assertIn(key, data["pipeline"])
        for key in ("total_spend", "attributed_revenue", "roas", "net", "cpl", "cac"):
            self.assertIn(key, data["roi"])

    def test_drilldowns(self):
        D = self.env["sgc.crm.marketing.dashboard"]
        for kind in ("open", "won", "lost", "buyers", "aging",
                     "stage", "source", "owner", "campaign"):
            act = D.open_records(kind, {})
            self.assertEqual(act["type"], "ir.actions.act_window")
            self.assertTrue(act["res_model"])
        with self.assertRaises(Exception):
            D.open_records("nope", {})

    def test_campaign_cost_field(self):
        self.assertIn("marketing_cost", self.env["utm.campaign"]._fields)
