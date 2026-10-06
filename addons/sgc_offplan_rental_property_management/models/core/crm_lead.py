# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class PropertyInquiry(models.Model):
    # Odoo 19: a list `_inherit` needs an explicit `_name`, or the model name
    # is derived from the class name (Entry 52 PropertyMaintenance regression).
    # Keep the explicit name: this class extends crm.lead.
    _name = 'crm.lead'
    _inherit = ['crm.lead', 'sgc.critical.audit.mixin']

    # Entry 53 capture scope: lead identity + pipeline state + the estate links
    # this module adds. Related/computed fields and chatter stay out.
    _audit_watched_fields = frozenset({
        'name', 'type', 'stage_id', 'probability', 'expected_revenue',
        'partner_id', 'user_id', 'team_id', 'company_id',
        'email_from', 'phone', 'description',
        'property_id', 'ask_price', 'duration_id', 'booking_id',
        'tenancy_inquiry_id', 'sale_inquiry_id',
    })
    # Declared exemption (Entry 53): crm.merge.opportunity auto-unlinks duplicate
    # leads (auto_unlink=True) inside one transaction with no reason path;
    # gating deletes would break the standard merge. Unlinks are still captured,
    # as tier-2 events.
    _audit_unlink_requires_reason = False

    property_id = fields.Many2one('property.details', string='Property',
                                   domain="['|',('state','=','available'),('state','=','sold')]")
    sale_lease = fields.Selection(related='property_id.sale_lease')
    price = fields.Monetary(related="property_id.price")

    # For sale
    company_id = fields.Many2one('res.company',
                                 string='Company',
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency',
                                  related='company_id.currency_id',
                                  string='Currency ')
    ask_price = fields.Monetary(string="Ask Price")

    # DEPRECATED
    duration_id = fields.Many2one('contract.duration', string='Duration')
    booking_id = fields.Many2one("property.vendor", string="Booking")
    tenancy_inquiry_id = fields.Many2one('tenancy.inquiry',
                                         string="Rent Enquiry")
    sale_inquiry_id = fields.Many2one('sale.inquiry', string="Sale Enquiry")
