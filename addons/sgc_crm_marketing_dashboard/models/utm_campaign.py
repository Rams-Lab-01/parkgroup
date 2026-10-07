# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from odoo import fields, models


class UtmCampaign(models.Model):
    """Capture marketing spend so campaign ROI can be computed for real.

    Odoo's UTM campaign has no cost field, so 'ROI' is impossible without it.
    This adds the spend input the dashboard divides attributable revenue by.
    """
    _inherit = "utm.campaign"

    marketing_cost = fields.Monetary(
        string="Marketing Cost",
        currency_field="cost_currency_id",
        help="Total spend on this campaign (ads, agency, media). Used by the "
             "CRM & Marketing dashboard to compute CPL, CPA and ROAS.")
    cost_currency_id = fields.Many2one(
        "res.currency", string="Cost Currency",
        default=lambda self: self.env.company.currency_id)
