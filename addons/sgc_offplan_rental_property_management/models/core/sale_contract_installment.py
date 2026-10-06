# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleContractInstallment(models.Model):
    _name = 'sale.contract.installment'
    _description = 'Sale Contract Installment'
    _inherit = ['sgc.critical.audit.mixin']
    _order = 'contract_id, sequence, due_date'

    contract_id = fields.Many2one(
        'sale.contract',
        string='Sale Contract',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Description', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    due_date = fields.Date(string='Due Date')
    amount = fields.Monetary(
        string='Amount',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='contract_id.currency_id',
        store=True,
        readonly=True,
    )
    percentage = fields.Float(string='Percentage (%)', digits=(5, 2))
    invoice_id = fields.Many2one(
        'account.move',
        string='Invoice',
        ondelete='set null',
        index=True,
        help='Customer invoice generated for this installment.',
    )
    state = fields.Selection([
        ('pending', 'Pending'),
        ('invoiced', 'Invoiced'),
        ('paid', 'Paid'),
        ('partial', 'Partially Paid'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ], string='Status', compute='_compute_state', store=True, default='pending')
    payment_date = fields.Date(string='Payment Date')
    notes = fields.Text(string='Notes')

    @api.depends('invoice_id.payment_state', 'invoice_id.amount_residual',
                 'invoice_id.amount_total', 'invoice_id.state',
                 'due_date')
    def _compute_state(self):
        today = fields.Date.context_today(self)
        for line in self:
            inv = line.invoice_id
            if inv and inv.state == 'cancel':
                line.state = 'cancelled'
                continue
            if inv and inv.state == 'posted':
                ps = inv.payment_state
                if ps == 'paid':
                    line.state = 'paid'
                elif ps == 'partial':
                    line.state = 'partial'
                elif ps in ('not_paid', 'in_payment', 'reversed'):
                    line.state = 'overdue' if line.due_date and line.due_date < today else 'invoiced'
                else:
                    line.state = 'invoiced'
                continue
            if line.due_date and line.due_date < today:
                line.state = 'overdue'
            else:
                line.state = 'pending'

    def action_generate_invoice(self):
        self.ensure_one()
        self._generate_invoices(post=True)
        return True

    def action_generate_invoices_bulk(self):
        return self._generate_invoices(post=True)

    def _generate_invoices(self, post=False):
        AccountMove = self.env['account.move']
        for line in self:
            if line.invoice_id:
                continue
            contract = line.contract_id
            if not contract.buyer_id:
                raise UserError(_('Cannot generate invoice for installment on contract %s - no buyer is set.') % contract.display_name)
            product = line._get_invoice_product()
            line_vals = {
                'name': _('%s - %s') % (contract.display_name, line.name),
                'quantity': 1,
                'price_unit': line.amount,
            }
            if product:
                line_vals['product_id'] = product.id
                if product.taxes_id:
                    line_vals['tax_ids'] = [(6, 0, product.taxes_id.ids)]
                income_account = product.product_tmpl_id._get_product_accounts().get('income')
                if income_account:
                    line_vals['account_id'] = income_account.id
            move = AccountMove.create({
                'move_type': 'out_invoice',
                'partner_id': contract.buyer_id.id,
                'invoice_date': line.due_date or fields.Date.context_today(self),
                'invoice_origin': contract.name,
                'sold_id': contract.id,
                'currency_id': contract.currency_id.id,
                'invoice_line_ids': [(0, 0, line_vals)],
            })
            if post:
                move.action_post()
            line.invoice_id = move.id

    def _get_invoice_product(self):
        product = self.env['product.product'].search([
            ('default_code', '=', 'INSTALLMENT'),
            ('company_id', 'in', [False, self.env.company.id]),
        ], limit=1)
        if product:
            return product
        fallback = self.env.ref(
            'sgc_offplan_rental_property_management.property_product_1',
            raise_if_not_found=False,
        )
        return fallback if fallback and fallback.exists() else None

    def action_view_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_('No invoice has been generated for this installment yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Installment Invoice'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.invoice_id.id,
        }

    def action_mark_paid(self):
        return self.action_generate_invoice()

    def action_mark_overdue(self):
        return True
