# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class PropertySpecification(models.Model):
    _name = 'property.specification'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Property Specifications'
    _order = 'title'

    # Audit capture scope (Entry 51): the label and the descriptive text shown
    # on listings. `image` is media.
    _audit_watched_fields = frozenset({
        'title',
        'description',
    })

    image = fields.Binary(string='Image')
    title = fields.Char(string='Title', required=True)
    description = fields.Text(string='Description')
