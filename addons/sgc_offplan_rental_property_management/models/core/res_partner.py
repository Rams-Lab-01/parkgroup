# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import models, fields, api


class UserTypes(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'sgc.critical.audit.mixin']

    user_type = fields.Selection([('landlord', 'LandLord'),
                                  ('customer', 'Customer'),
                                  ('broker', 'Broker'),
                                  ('tenant', 'Tenant')],
                                 string='User Type')
    properties_count = fields.Integer(string='Properties Count', compute='_compute_properties_count')
    properties_ids = fields.One2many('property.details', 'landlord_id', string='Managed Properties')
    favorite_property_ids = fields.Many2many(
        'property.details', 'res_partner_favorite_property_rel',
        'partner_id', 'property_id',
        string='Favorite Properties')
    brokerage_company_id = fields.Many2one('res.company', string=' Brokerage Company',
                                           default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='brokerage_company_id.currency_id',
                                  string='Currency')

    # Customer Fields
    is_tenancy = fields.Boolean(string='Property Renting')
    is_sold_customer = fields.Boolean(string='Property Buyer')

    # Broker Fields
    tenancy_ids = fields.One2many('tenancy.details', 'broker_id', string='Tenancy ')
    property_sold_ids = fields.One2many('property.vendor', 'broker_id', string="Sold Commission")

    def _portal_property_menu(self):
        """Which property-management portal entries have data for this account.

        Drives the "smart" /my tiles: an entry is shown only when it has something
        to show, so a plain customer never sees an empty landlord/tenant folder.
        """
        self.ensure_one()
        env, pid = self.env, self.id
        has = lambda model, domain: bool(env[model].sudo().search_count(domain, limit=1))
        return {
            'lease': has('rent.contract', [('tenant_id', '=', pid)]) or has('tenancy.details', [('tenant_id', '=', pid)]),
            'portfolio': has('property.details', [('landlord_id', '=', pid)]) or has('rent.contract', [('landlord_id', '=', pid)]),
            'favorites': bool(self.sudo().favorite_property_ids),
            'inquiries': has('crm.lead', [('partner_id', '=', pid), ('property_id', '!=', False)]),
            'purchases': has('sale.contract', [('buyer_id', '=', pid)]),
        }

    @api.depends('properties_ids')
    def _compute_properties_count(self):
        for rec in self:
            count = self.env['property.details'].search_count([('landlord_id', '=', rec.id)])
            rec.properties_count = count

    def action_properties(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Properties',
            'res_model': 'property.details',
            'domain': [('landlord_id', '=', self.id)],
            'context': {'default_landlord_id': self.id},
            'view_mode': 'list,form',
            'target': 'current'
        }

