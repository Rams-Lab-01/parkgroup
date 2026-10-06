# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleInquiry(models.Model):
    _name = 'sale.inquiry'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Sale Inquiry'
    _order = 'id desc'

    # Entry 52 scope: the whole inquiry lifecycle.
    _audit_watched_fields = frozenset({
        'name', 'property_id', 'buyer_id', 'inquiry_date', 'state',
    })

    name = fields.Char(string='Reference', required=True)
    property_id = fields.Many2one('property.details', string='Property')
    buyer_id = fields.Many2one('res.partner', string='Buyer')
    inquiry_date = fields.Date(string='Inquiry Date')
    state = fields.Selection([
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('closed', 'Closed'),
    ], string='Status', default='new')
