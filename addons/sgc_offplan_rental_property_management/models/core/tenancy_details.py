# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class TenancyDetails(models.Model):
    _name = 'tenancy.details'
    _description = 'Tenancy Details'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _order = 'id desc'

    name = fields.Char(string='Tenancy Reference', required=True)
    property_id = fields.Many2one('property.details', string='Property', index=True)
    tenant_id = fields.Many2one('res.partner', string='Tenant', required=True)
    landlord_id = fields.Many2one('res.partner', string='Landlord')
    broker_id = fields.Many2one('res.partner', string='Broker')
    start_date = fields.Date(string='Start Date')
    end_date = fields.Date(string='End Date')
    rent_amount = fields.Monetary(string='Rent Amount', currency_field='currency_id')
    total_rent = fields.Monetary(string='Total Rent', currency_field='currency_id')
    month = fields.Integer(string='Month')
    is_any_broker = fields.Boolean(string='Has Broker', default=False)
    currency_id = fields.Many2one('res.currency', string='Currency')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft')
    type = fields.Selection([
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
        ('industrial', 'Industrial'),
        ('land', 'Land'),
    ], string='Type', default='residential')
    is_extra_service = fields.Boolean(string='Extra Service', default=False)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    tenancy_seq = fields.Char(string='Tenancy Seq')
    notes = fields.Text(string='Notes')
    tenancy_id = fields.Many2one('rent.contract', string='Rent Contract')
    property_type = fields.Selection([
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
        ('industrial', 'Industrial'),
        ('land', 'Land'),
    ], string='Property Type', default='residential')
    property_landlord_id = fields.Many2one('res.partner', string='Property Landlord')
    duration_id = fields.Many2one('contract.duration', string='Duration')
    broker_invoice_id = fields.Many2one('account.move', string='Broker Invoice', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('tenancy.details') or _('New')
        return super(TenancyDetails, self).create(vals_list)

    def action_activate(self):
        for rec in self:
            rec.state = 'active'

    def action_expire(self):
        for rec in self:
            rec.state = 'expired'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

