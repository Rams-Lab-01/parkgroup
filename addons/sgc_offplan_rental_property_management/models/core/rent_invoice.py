# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RentInvoice(models.Model):
    _name = 'rent.invoice'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _description = 'Rent Invoice'
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True)
    contract_id = fields.Many2one('rent.contract', string='Contract')
    invoice_id = fields.Many2one('account.move', string='Invoice')
    tenant_id = fields.Many2one('res.partner', string='Tenant')
    amount = fields.Monetary(string='Amount', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string='Currency')
    invoice_date = fields.Date(string='Invoice Date')
    due_date = fields.Date(string='Due Date')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    # Fields referenced by rent_invoice_view.xml
    tenancy_id = fields.Many2one('tenancy.details', string='Tenancy')
    customer_id = fields.Many2one('res.partner', string='Customer')
    landlord_id = fields.Many2one('res.partner', string='Landlord')
    is_extra_service = fields.Boolean(string='Is Extra Service')
    rent_invoice_id = fields.Many2one('account.move', string='Rent Invoice Ref')
    payment_state = fields.Selection([
        ('not_paid', 'Not Paid'),
        ('in_payment', 'In Payment'),
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('reversed', 'Reversed'),
    ], string='Payment Status', default='not_paid')
    rent_amount = fields.Monetary(string='Rent Amount', currency_field='currency_id')
    installment_type = fields.Selection([
        ('manual', 'Manual'),
        ('automatic', 'Automatic'),
    ], string='Installment Type', default='automatic')
    service_amount = fields.Monetary(string='Service Amount', currency_field='currency_id')
    type = fields.Selection([
        ('rent', 'Rent'),
        ('service', 'Service'),
        ('deposit', 'Deposit'),
    ], string='Type', default='rent')
    description = fields.Text(string='Description')
    invoice_count = fields.Integer(string='Invoice Count', compute='_compute_invoice_count')
    contract_count = fields.Integer(string='Contract Count', compute='_compute_contract_count')

    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = 1 if rec.rent_invoice_id else 0

    def _compute_contract_count(self):
        for rec in self:
            rec.contract_count = 1 if rec.contract_id else 0

    def action_confirm(self):
        for rec in self:
            rec.state = 'open'

    def action_pay(self):
        for rec in self:
            rec.state = 'paid'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    def action_draft(self):
        for rec in self:
            rec.state = 'draft'

    def action_view_invoice(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoice',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.rent_invoice_id.id,
        }

    def action_view_contract(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Rent Contract',
            'res_model': 'rent.contract',
            'view_mode': 'form',
            'res_id': self.contract_id.id,
        }
