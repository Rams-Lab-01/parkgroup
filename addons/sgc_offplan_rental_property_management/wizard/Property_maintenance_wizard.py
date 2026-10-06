# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class PropertyMaintenance(models.TransientModel):
    _name = 'maintenance.wizard'
    _description = 'Crating Maintenance Request'

    name = fields.Char(string='Request', translate=True)
    property_id = fields.Many2one('property.details', string='Property')
    rent_contract_id = fields.Many2one('tenancy.details', string="Rent Contract")
    sell_contract_id = fields.Many2one('property.vendor', string="Sell Contract")
    maintenance_type_id = fields.Many2one('product.template',
                                          string='Type',
                                          domain=[('is_maintenance', '=', True)])
    maintenance_team_id = fields.Many2one('maintenance.team', string='Team')
    is_property_maintenance = fields.Boolean(string="Property Maintenance")
    is_renting_contract_maintenance = fields.Boolean(string="Renting Contract Maintenance")
    is_selling_contract_maintenance = fields.Boolean(string="Selling Contract Maintenance")

    # Default Get
    @api.model
    def default_get(self, fields):
        res = super(PropertyMaintenance, self).default_get(fields)
        current_context = self._context
        is_property_maintenance = current_context.get('is_property_maintenance')
        is_renting_contract_maintenance = current_context.get('is_renting_contract_maintenance')
        is_selling_contract_maintenance = current_context.get('is_selling_contract_maintenance')
        active_id = current_context.get('active_id')
        if is_property_maintenance:
            res['property_id'] = active_id
        elif is_renting_contract_maintenance:
            res['rent_contract_id'] = active_id
        else:
            res['sell_contract_id'] = active_id
        res['is_property_maintenance'] = is_property_maintenance
        res['is_renting_contract_maintenance'] = is_renting_contract_maintenance
        res['is_selling_contract_maintenance'] = is_selling_contract_maintenance
        return res

    def maintenance_request(self):
        data = {
            'name': self.name,
            'landlord_id': self.property_id.landlord_id.id,
            'maintenance_type_id': self.maintenance_type_id.id,
            'maintenance_team_id': self.maintenance_team_id.id,
            'request_date': fields.Date.today()
        }

        if self.is_property_maintenance:
            data['property_id'] = self.property_id.id
        elif self.is_renting_contract_maintenance:
            data['rent_contract_id'] = self.rent_contract_id.id
            data['property_id'] = self.rent_contract_id.property_id.id
            data['customer_id'] = self.rent_contract_id.tenancy_id.id
        else:
            data['sell_contract_id'] = self.sell_contract_id.id
            data['property_id'] = self.sell_contract_id.property_id.id
            data['customer_id'] = self.sell_contract_id.customer_id.id

        self.env['maintenance.request'].create(data)
