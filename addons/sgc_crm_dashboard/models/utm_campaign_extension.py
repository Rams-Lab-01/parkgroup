# -*- coding: utf-8 -*-
# Part of CRM Executive Dashboard. See LICENSE file for full copyright and licensing details.
from odoo import fields, models


class UtmCampaign(models.Model):
    _inherit = 'utm.campaign'

    ced_currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    ced_budget = fields.Monetary(
        string='Budget / Cost', currency_field='ced_currency_id',
        help="Planned or actual spend for this campaign. Used by the CRM "
             "Executive Dashboard to compute ROI (won revenue vs. budget).",
    )
