# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import fields, models, api


class RentBill(models.Model):
    _name = 'rent.bill'
    _description = 'Rent Bill'
    _rec_name = 'rent_no'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']

    # rent.contract is the canonical renting model (it has the UI/menu and is the
    # only reachable bill-generation path); tenancy_id is retained only for the
    # legacy property.payment.wizard path. All business fields below now source
    # from contract_id so they populate for bills created by the real flow.
    contract_id = fields.Many2one('rent.contract', string='Rent Contract', ondelete='cascade', index=True)
    tenancy_id = fields.Many2one('tenancy.details', string='Tenancy')
    rent_no = fields.Char(string='Rent No.', index=True, copy=False)
    customer_id = fields.Many2one(related='contract_id.tenant_id', string='Customer', store=True)
    vendor_id = fields.Many2one('res.partner', string="Vendor")
    bill_type = fields.Char(string='Payment')
    invoice_date = fields.Date(string='Bill Date')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency',
                                  related='company_id.currency_id',
                                  string='Currency')
    installment_type = fields.Selection(related="contract_id.payment_frequency",
                                        string="Installment Type", store=True)

    # Calculation
    amount = fields.Monetary(string='Amount ')
    rent_amount = fields.Monetary(string='Rent Amount')

    description = fields.Char(string='Description', translate=True)
    rent_bill_id = fields.Many2one('account.move', string='Bill')
    payment_state = fields.Selection(related='rent_bill_id.payment_state',
                                     string="Payment Status")
    landlord_id = fields.Many2one(related="contract_id.landlord_id",
                                  store=True)
    tenancy_type = fields.Selection(related="contract_id.property_id.property_type",
                                    string="Rent Type", store=True)
    service_amount = fields.Monetary(string="Extra Amount",
                                     help="Recurring Utility Service (if any) + Recurring Maintenance Service (if any)")
    is_extra_service = fields.Boolean(string="Extra Service", default=False)
    bill_count = fields.Integer(string='Bill Count', compute='_compute_bill_count')
    contract_count = fields.Integer(string='Contract Count', compute='_compute_contract_count')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('rent_no'):
                vals['rent_no'] = self.env['ir.sequence'].next_by_code('rent.bill') or _('New')
        return super(RentBill, self).create(vals_list)

    def _compute_bill_count(self):
        for rec in self:
            rec.bill_count = 1 if rec.rent_bill_id else 0

    def _compute_contract_count(self):
        for rec in self:
            rec.contract_count = 1 if rec.contract_id else 0

    def action_view_bill(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Bill',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.rent_bill_id.id,
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
