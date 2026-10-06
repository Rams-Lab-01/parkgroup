# -*- coding: utf-8 -*-
from odoo import api, fields, models


class PropertyResCity(models.Model):
    _name = 'property.res.city'
    _inherit = ['mail.thread', 'mail.activity.mixin',
                'sgc.critical.audit.mixin']
    _description = 'Property City'
    _order = 'name'

    # Audit capture scope (Entry 51): the city name and its administrative
    # anchors. `color` is cosmetic UI state and stays out of scope.
    _audit_watched_fields = frozenset({
        'name',
        'region_id',
        'state_id',
        'country_id',
    })

    name = fields.Char(string='City Name', required=True)
    region_id = fields.Many2one('property.region', string='Region')
    state_id = fields.Many2one('res.country.state', string='State')
    country_id = fields.Many2one('res.country', string='Country')
    color = fields.Integer(string="Color")
