# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

from odoo import fields, models


class CertificateType(models.Model):
    _name = 'certificate.type'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Certificate Types'
    _order = 'type'

    # Audit capture scope (Entry 51): the certificate type label is the
    # model's only field.
    _audit_watched_fields = frozenset({
        'type',
    })

    type = fields.Char(string='Type', required=True)
