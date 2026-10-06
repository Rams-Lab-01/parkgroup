# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PropertySaleTenancyXlsReport(models.TransientModel):
    _name = 'property.sale.tenancy.xls.report'
    _description = 'Property Sale Tenancy XLS Report'

    date_from = fields.Date(string='From Date')
    date_to = fields.Date(string='To Date')

    def action_generate_report(self):
        return {'type': 'ir.actions.act_window_close'}
