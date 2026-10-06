# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ParentProperty(models.Model):
    _name = 'parent.property'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Parent Property'
    _order = 'name'

    # Entry 52 scope: identity, grouping, price. `active` is excluded estate-wide.
    _audit_watched_fields = frozenset({
        'name', 'code', 'project_id', 'region_id', 'price', 'company_id',
    })

    name = fields.Char(string='Property Name', required=True)
    code = fields.Char(string='Code')
    project_id = fields.Many2one('property.project', string='Project')
    region_id = fields.Many2one('property.region', string='Region')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Currency')
    price = fields.Monetary(string='Price', currency_field='currency_id')
    active = fields.Boolean(string='Active', default=True)
