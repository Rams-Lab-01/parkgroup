# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PropertyVendorWizard(models.TransientModel):
    _name = 'property.vendor.wizard'
    _description = 'Property Vendor Wizard'

    property_id = fields.Many2one('property.details', string='Property')
    vendor_id = fields.Many2one('res.partner', string='Vendor')

    def action_assign_vendor(self):
        return {'type': 'ir.actions.act_window_close'}
