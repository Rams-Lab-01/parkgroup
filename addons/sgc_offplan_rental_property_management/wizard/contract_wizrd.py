# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ContractWizard(models.TransientModel):
    _name = 'rent.contract.wizard'
    _description = 'Rent Contract Wizard'

    property_id = fields.Many2one('property.details', string='Property')
    tenant_id = fields.Many2one('res.partner', string='Tenant')
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    rent_amount = fields.Monetary(string='Rent Amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency')

    def action_create_contract(self):
        return {'type': 'ir.actions.act_window_close'}
