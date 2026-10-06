# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class PropertyTag(models.Model):
    _name = 'property.tag'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Property Tags'
    _order = 'title'

    # Audit capture scope (Entry 51): the tag label is the model's only field.
    _audit_watched_fields = frozenset({
        'title',
    })

    title = fields.Char(string='Title', required=True)
