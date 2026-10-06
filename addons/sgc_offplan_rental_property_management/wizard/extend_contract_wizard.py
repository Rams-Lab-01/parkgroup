# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import models, api, fields


class ExtendContract(models.TransientModel):
    _name = 'extend.contract.wizard'
    _description = 'Wizard for extend contract'

    tenancy_id = fields.Many2one('tenancy.details', string='Tenancy')
    duration_id = fields.Many2one('contract.duration', string='Duration')
    customer_id = fields.Many2one(related='tenancy_id.tenant_id', string='Customer')
    property_id = fields.Many2one(related='tenancy_id.property_id', string='Property')
    duration_id = fields.Many2one('contract.duration', string='Extend Duration')
    month = fields.Integer(related='duration_id.month', string='Month')
    start_date = fields.Date(related='tenancy_id.end_date', string='Start Date')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency')
    revised_price = fields.Monetary(string='Revised Price')
    is_any_broker = fields.Boolean(related='tenancy_id.is_any_broker', string='Broker ')
    new_broker_id = fields.Many2one(related='tenancy_id.broker_id', string='Broker', readonly=False)
    payment_term = fields.Selection([('monthly', 'Monthly'),
                                     ('full_payment', 'Full Payment')],
                                    string='Payment Term')

    @api.onchange('tenancy_id')
    def revised_price_relate(self):
        for rec in self:
            if rec.tenancy_id:
                rent = rec.tenancy_id.total_rent
                rec.revised_price = rent
            else:
                return True

    def extend_contract_action(self):
        invoice_post_type = self.env['ir.config_parameter'].sudo().get_param('sgc_offplan_rental_property_management.invoice_post_type')
        if self.payment_term == 'monthly':
            self.customer_id.is_tenancy = True
            record = {
                'tenancy_id': self.customer_id.id,
                'property_id': self.property_id.id,
                'is_any_broker': self.is_any_broker,
                'broker_id': self.new_broker_id.id,
                'duration_id': self.duration_id.id,
                'start_date': self.start_date,
                'total_rent': self.revised_price,
                'contract_type': 'new_contract',
                'is_extra_service': self.tenancy_id.is_extra_service,
                'payment_term': self.payment_term,
                'is_extended': True
            }
            new_tenancy_id = self.env['tenancy.details'].create(record)
            self.tenancy_id.contract_type = 'close_contract'
            self.tenancy_id.close_contract_state = True
            self.property_id.stage = 'on_lease'
        else:
            record = {
                'tenancy_id': self.customer_id.id,
                'property_id': self.property_id.id,
                'is_any_broker': self.is_any_broker,
                'broker_id': self.new_broker_id.id,
                'duration_id': self.duration_id.id,
                'start_date': self.start_date,
                'total_rent': self.revised_price,
                'is_extra_service': self.tenancy_id.is_extra_service,
                'contract_type': 'running_contract',
                'last_invoice_payment_date': fields.Date.today(),
                'payment_term': self.payment_term,
                'active_contract_state': True,
                'is_extended': True
            }
            new_tenancy_id = self.env['tenancy.details'].create(record)
            self.tenancy_id.contract_type = 'close_contract'
            self.tenancy_id.close_contract_state = True
            self.property_id.stage = 'on_lease'

            # Creating Invoice
            amount = self.revised_price
            total_amount = amount * self.duration_id.month
            full_payment_record = {
                'product_id': self.env.ref('sgc_offplan_rental_property_management.property_product_1').id,
                'name': 'Full Payment of ' + self.property_id.name,
                'quantity': 1,
                'price_unit': total_amount
            }
            invoice_lines = [(0, 0, full_payment_record)]
            data = {
                'partner_id': self.customer_id.id,
                'move_type': 'out_invoice',
                'invoice_date': fields.Date.today(),
                'invoice_line_ids': invoice_lines
            }
            invoice_id = self.env['account.move'].sudo().create(data)
            invoice_id.tenancy_id = new_tenancy_id.id
            if invoice_post_type == 'automatically':
                invoice_id.action_post()

            rent_invoice = {
                'tenancy_id': new_tenancy_id.id,
                'type': 'rent',
                'invoice_date': fields.Date.today(),
                'amount': total_amount,
                'description': 'Full Payment Of Rent',
                'rent_invoice_id': invoice_id.id
            }
            rent_invoice_id = self.env['rent.invoice'].create(rent_invoice)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Contract',
            'res_model': 'tenancy.details',
            'res_id': new_tenancy_id.id,
            'view_mode': 'form,list',
            'target': 'current'
        }
