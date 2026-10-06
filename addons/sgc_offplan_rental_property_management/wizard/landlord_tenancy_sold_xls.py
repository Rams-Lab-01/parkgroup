# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LandlordTenancySoldXls(models.TransientModel):
    _name = 'landlord.tenancy.sold.xls'
    _description = 'Landlord Tenancy Sold XLS'

    date_from = fields.Date(string='From Date')
    date_to = fields.Date(string='To Date')

    def action_generate_report(self):
        return {'type': 'ir.actions.act_window_close'}
