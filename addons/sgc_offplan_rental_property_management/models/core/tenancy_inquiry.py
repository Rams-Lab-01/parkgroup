# -*- coding: utf-8 -*-
from odoo import api, fields, models


class TenancyInquiry(models.Model):
    _name = 'tenancy.inquiry'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Tenancy Inquiry'
    _order = 'id desc'

    # Audit capture scope (Entry 44): the whole record is meaningful - the
    # reference, the property and tenant it points at, its date and state.
    _audit_watched_fields = frozenset({
        'name',
        'property_id',
        'tenant_id',
        'inquiry_date',
        'state',
    })

    name = fields.Char(string='Reference', required=True)
    property_id = fields.Many2one('property.details', string='Property')
    tenant_id = fields.Many2one('res.partner', string='Tenant')
    inquiry_date = fields.Date(string='Inquiry Date')
    state = fields.Selection([
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('closed', 'Closed'),
    ], string='Status', default='new')
