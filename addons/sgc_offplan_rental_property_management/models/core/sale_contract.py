# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import timedelta
from dateutil.relativedelta import relativedelta

from odoo.addons.sgc_offplan_rental_property_management.models.core.payment_schedule import (
    _project_plan_rows,
    _reconcile_plan_rows,
)


class SaleContract(models.Model):
    _name = 'sale.contract'
    _description = 'Sale Contract'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Contract Reference',
        required=True,
        tracking=True,
        default=lambda self: _('New'),
        copy=False,
    )
    property_id = fields.Many2one(
        'property.details',
        string='Property',
        required=True,
        tracking=True,
    )
    buyer_id = fields.Many2one(
        'res.partner',
        string='Buyer',
        required=True,
        tracking=True,
    )
    seller_id = fields.Many2one(
        'res.partner',
        string='Seller',
        tracking=True,
    )
    sale_price = fields.Monetary(
        string='Sale Price',
        currency_field='currency_id',
        tracking=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    contract_date = fields.Date(
        string='Contract Date',
        default=fields.Date.context_today,
        tracking=True,
    )
    handover_date = fields.Date(string='Handover Date')
    payment_schedule_id = fields.Many2one(
        'payment.schedule',
        string='Payment Schedule',
        domain=[('schedule_type', '=', 'sale')],
    )
    booking_amount = fields.Monetary(
        string='Booking Amount',
        currency_field='currency_id',
        help='Deposit paid upfront at time of booking.',
    )
    notes = fields.Text(string='Notes')
    signed_via_portal = fields.Boolean(
        string='Signed via Portal',
        default=False,
        help='Marked when the customer clicked "I agree & sign" from the portal.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('signed', 'Signed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
    )

    # -------------------------------------------------------------------------
    # Commission Distribution (dynamic lines)
    # -------------------------------------------------------------------------
    commission_line_ids = fields.One2many(
        'property.commission.line', 'contract_id',
        string='Commission Lines',
        help='Dynamic commission distribution to external and internal parties',
    )
    commission_total_amount = fields.Monetary(
        string='Total Commission', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
    )
    commission_external_total = fields.Monetary(
        string='External Commission Total', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
    )
    commission_internal_total = fields.Monetary(
        string='Internal Commission Total', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
    )
    commission_line_count = fields.Integer(
        string='Commission Line Count',
        compute='_compute_commission_line_count',
    )
    commission_total_tax = fields.Monetary(
        string='Total Tax', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
        help='Sum of tax across all commission lines.')
    commission_amount_total = fields.Monetary(
        string='Total w/ Tax', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
        help='Grand total of commission lines including tax.')

    @api.depends('commission_line_ids.commission_amount',
                 'commission_line_ids.amount_tax',
                 'commission_line_ids.amount_total')
    def _compute_commission_totals(self):
        for rec in self:
            lines = rec.commission_line_ids
            rec.commission_external_total = sum(
                l.commission_amount for l in lines if l.category == 'external'
            )
            rec.commission_internal_total = sum(
                l.commission_amount for l in lines if l.category == 'internal'
            )
            # Sum every line regardless of category (not just external + internal)
            # so an 'others' line isn't silently dropped from the grand total.
            rec.commission_total_amount = sum(lines.mapped('commission_amount'))
            rec.commission_total_tax = sum(lines.mapped('amount_tax'))
            rec.commission_amount_total = sum(lines.mapped('amount_total'))

    @api.depends('commission_line_ids')
    def _compute_commission_line_count(self):
        for rec in self:
            rec.commission_line_count = len(rec.commission_line_ids)

    # -------------------------------------------------------------------------
    # Commission eligibility gate — checked server-side inside
    # commission.line.mixin._generate_bills before any bill is
    # raised, not just hidden in the UI.
    # -------------------------------------------------------------------------
    is_commission_eligible = fields.Boolean(
        string='Commission Eligible', compute='_compute_commission_eligibility')
    commission_ineligible_reason = fields.Char(
        string='Commission Ineligibility Reason', compute='_compute_commission_eligibility')

    @api.depends('payment_schedule_id', 'sale_price', 'overall_payment_state',
                 'installment_ids.amount', 'installment_ids.state')
    def _compute_commission_eligibility(self):
        threshold = float(self.env['ir.config_parameter'].sudo().get_param(
            'sgc_offplan_rental_property_management.commission_eligibility_sale_pct', 20.0))
        for contract in self:
            if contract.payment_schedule_id:
                paid = sum(l.amount for l in contract.installment_ids if l.state == 'paid')
                pct = (paid / contract.sale_price * 100.0) if contract.sale_price else 0.0
                if pct >= threshold:
                    contract.is_commission_eligible = True
                    contract.commission_ineligible_reason = False
                else:
                    contract.is_commission_eligible = False
                    contract.commission_ineligible_reason = _(
                        'Only %.1f%% of the sale price has been paid; %.0f%% is required '
                        'before commission can be billed.'
                    ) % (pct, threshold)
            else:
                if contract.overall_payment_state == 'paid':
                    contract.is_commission_eligible = True
                    contract.commission_ineligible_reason = False
                else:
                    contract.is_commission_eligible = False
                    contract.commission_ineligible_reason = _(
                        'This is a full-payment sale; commission is eligible once the sale '
                        'is fully paid.'
                    )

    def action_create_commission_line(self):
        self.ensure_one()
        return {
            'name': _('Add Commission Line'),
            'type': 'ir.actions.act_window',
            'res_model': 'property.commission.line',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_contract_id': self.id,
                'default_currency_id': self.currency_id.id,
            },
        }

    # Installment relation
    installment_ids = fields.One2many(
        'sale.contract.installment',
        'contract_id',
        string='Installments',
    )
    installment_count = fields.Integer(
        string='Installment Count',
        compute='_compute_installment_count',
    )
    total_paid = fields.Monetary(
        string='Total Paid',
        currency_field='currency_id',
        compute='_compute_total_paid',
        store=True,
    )

    # --------------------------------------------------------------------------
    # Collection metrics for the executive dashboard. Stored so the dashboard
    # query and the list view can filter/sort on these without recomputing.
    # --------------------------------------------------------------------------
    balance_due = fields.Monetary(
        string='Balance Due',
        currency_field='currency_id',
        compute='_compute_collection_metrics',
        store=True,
        help='Sale price minus total paid. Can be negative when a buyer is '
             'ahead (over-payment / refund).',
    )
    collection_pct = fields.Float(
        string='Collection %',
        compute='_compute_collection_metrics',
        store=True,
        digits=(5, 2),
        help='Paid share of the sale price (0..100). 100 when fully paid.',
    )
    last_activity_date = fields.Date(
        string='Last Activity Date',
        compute='_compute_last_activity_date',
        store=True,
        help='Most recent payment date on paid installments; falls back to the '
             'contract date. Used by the dashboard aging buckets.',
    )

    @api.depends('sale_price', 'total_paid')
    def _compute_collection_metrics(self):
        for contract in self:
            sale = contract.sale_price or 0.0
            paid = contract.total_paid or 0.0
            contract.balance_due = sale - paid
            contract.collection_pct = (paid / sale * 100.0) if sale else 0.0

    @api.depends('installment_ids.payment_date',
                 'installment_ids.state',
                 'installment_ids.amount',
                 'contract_date',
                 'create_date')
    def _compute_last_activity_date(self):
        for contract in self:
            paid_dates = [
                line.payment_date for line in contract.installment_ids
                if line.state == 'paid' and line.payment_date
            ]
            contract.last_activity_date = (
                max(paid_dates) if paid_dates else contract.contract_date or contract.create_date.date()
            )

    # --------------------------------------------------------------------------
    # Computes
    # --------------------------------------------------------------------------

    @api.depends('installment_ids')
    def _compute_installment_count(self):
        for contract in self:
            contract.installment_count = len(contract.installment_ids)

    @api.depends('installment_ids.amount', 'installment_ids.state')
    def _compute_total_paid(self):
        for contract in self:
            contract.total_paid = sum(
                line.amount for line in contract.installment_ids
                if line.state == 'paid'
            )

    def _report_payment_plan_lines(self):
        """Return the payment-plan rows for printable Sale reports.

        Prefers the generated installments when present; otherwise projects
        the selected payment.schedule template onto the contract (mirroring
        action_generate_installments calendar math) so reports render the plan
        as soon as a schedule is selected on the form. Rows are returned in
        booking-first order (schedule lines already sort booking/one-time
        first) and reconciled against the contract Sale Price so the displayed
        amounts always add back to the offer/contract total.

        Each row is a dict:
        {sequence, name, percentage, amount, due_date, state, reconciled}.
        """
        self.ensure_one()
        basis = self.sale_price or 0.0
        rows = []
        installments = self.installment_ids.sorted(
            key=lambda l: (l.sequence, l.due_date or ''))
        if installments:
            for line in installments:
                rows.append({
                    'sequence': line.sequence,
                    'name': line.name,
                    'percentage': line.percentage,
                    'amount': line.amount,
                    'due_date': line.due_date,
                    'state': line.state,
                })
            return self._reconcile_payment_plan_rows(rows, basis)
        if not self.payment_schedule_id or not self.contract_date:
            return rows
        return _project_plan_rows(self.payment_schedule_id, basis, self.contract_date)

    def _reconcile_payment_plan_rows(self, rows, basis):
        """Display-only reconciliation of the payment-plan rows.

        Delegates to the shared report helper in payment_schedule.py; kept as a
        named method so existing callers keep working.
        """
        return _reconcile_plan_rows(rows, basis)

    # -------------------------------------------------------------------------
    # State transitions
    # -------------------------------------------------------------------------

    def _assign_reference(self):
        for contract in self:
            if not contract.name or contract.name == _('New'):
                contract.name = self.env['ir.sequence'].next_by_code('sale.contract') or _('New')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.contract') or _('New')
        return super(SaleContract, self).create(vals_list)

    def action_sign(self):
        for contract in self:
            if contract.state != 'draft':
                raise UserError(_('Only draft contracts can be signed.'))
            contract._assign_reference()
            contract.state = 'signed'
            # Signing reserves the property; it isn't actually sold until the
            # contract is completed (handover/final payment) via action_complete.
            if contract.property_id:
                contract.property_id.state = 'booked'

    def action_complete(self):
        for contract in self:
            if contract.state != 'signed':
                raise UserError(_('Only signed contracts can be marked as completed.'))
            contract._assign_reference()
            contract.state = 'completed'
            if contract.property_id:
                contract.property_id.state = 'sold'

    def action_cancel(self):
        for contract in self:
            if contract.state in ('completed', 'cancelled'):
                raise UserError(_('Completed or already cancelled contracts cannot be cancelled.'))
            contract.state = 'cancelled'
            if contract.property_id:
                contract.property_id.state = 'available'

    # -------------------------------------------------------------------------
    # Installment generation
    # -------------------------------------------------------------------------

    def action_generate_installments(self):
        """Generate installment lines from the linked payment schedule template."""
        self.ensure_one()
        if not self.payment_schedule_id:
            raise UserError(_('Please select a Payment Schedule before generating installments.'))
        if not self.contract_date:
            raise UserError(_('Please set a Contract Date before generating installments.'))

        # Remove existing draft installments only
        draft_lines = self.installment_ids.filtered(lambda l: l.state == 'pending')
        draft_lines.unlink()

        sequence = 1
        installment_vals = []
        for line in self.payment_schedule_id.schedule_line_ids.sorted('sequence'):
            # Calendar interval in MONTHS per frequency. Recurring installments
            # are anchored to this line's FIRST due date (contract_date +
            # days_after) and advanced by whole calendar months, so every
            # installment falls on the same day of the month as the first one:
            # a monthly plan whose first installment is due 10 Nov 2026
            # continues 10 Dec, 10 Jan, ... The day is restored from the anchor
            # on every step, so short months clamp and recover (31 Jan ->
            # 28 Feb -> 31 Mar).
            #
            # Was: contract_date + (days_after + 30/90/180/365 * i), which
            # drifts off the calendar - 30-day "months" move the day by one to
            # two days per year and 365-day "years" ignore leap years.
            months_step = {
                'monthly': 1,
                'quarterly': 3,
                'bi_annual': 6,
                'annual': 12,
            }.get(line.installment_frequency, 0)

            n = max(line.number_of_installments, 1)
            first_due = self.contract_date + timedelta(days=line.days_after)
            # Amount per installment split
            if n > 1 and months_step > 0:
                amount_each = (self.sale_price * line.percentage / 100.0) / n
                for i in range(n):
                    due = first_due + relativedelta(months=months_step * i)
                    installment_vals.append({
                        'contract_id': self.id,
                        'name': '%s — %d/%d' % (line.name, i + 1, n),
                        'sequence': sequence,
                        'due_date': due,
                        'percentage': line.percentage / n,
                        'amount': amount_each,
                        'state': 'pending',
                        'currency_id': self.currency_id.id,
                    })
                    sequence += 1
            else:
                due = first_due
                installment_vals.append({
                    'contract_id': self.id,
                    'name': line.name,
                    'sequence': sequence,
                    'due_date': due,
                    'percentage': line.percentage,
                    'amount': self.sale_price * line.percentage / 100.0,
                    'state': 'pending',
                    'currency_id': self.currency_id.id,
                })
                sequence += 1

        self.env['sale.contract.installment'].create(installment_vals)

    # -------------------------------------------------------------------------
    # Smart button action
    # -------------------------------------------------------------------------

    def action_view_installments(self):
        self.ensure_one()
        return {
            'name': _('Installments'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.contract.installment',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
            'context': {'default_contract_id': self.id},
        }

    # -------------------------------------------------------------------------
    # Invoices smart button (invoices generated from installments)
    # -------------------------------------------------------------------------

    invoice_ids = fields.Many2many(
        'account.move',
        compute='_compute_invoice_ids',
        string='Invoices',
    )
    invoice_count = fields.Integer(
        string='Invoice Count',
        compute='_compute_invoice_ids',
    )

    @api.depends('installment_ids.invoice_id')
    def _compute_invoice_ids(self):
        for contract in self:
            invoices = contract.installment_ids.invoice_id
            contract.invoice_ids = invoices
            contract.invoice_count = len(invoices)

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'name': _('Invoices'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.invoice_ids.ids)],
            'context': {'create': False},
        }

    # -------------------------------------------------------------------------
    # Commission bills smart button (vendor bills generated from commission
    # lines)
    # -------------------------------------------------------------------------

    commission_bill_ids = fields.Many2many(
        'account.move',
        relation='sale_contract_commission_bill_rel',
        compute='_compute_commission_bill_ids',
        string='Commission Bills',
    )
    commission_bill_count = fields.Integer(
        string='Commission Bill Count',
        compute='_compute_commission_bill_ids',
    )

    @api.depends('commission_line_ids.bill_id')
    def _compute_commission_bill_ids(self):
        for contract in self:
            bills = contract.commission_line_ids.bill_id
            contract.commission_bill_ids = bills
            contract.commission_bill_count = len(bills)

    def action_view_commission_bills(self):
        self.ensure_one()
        return {
            'name': _('Commission Bills'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.commission_bill_ids.ids)],
            'context': {'create': False},
        }

    # -------------------------------------------------------------------------
    # Overall payment status — summarizes the payment_state of every invoice
    # generated for this contract's installments, so the form/list can show
    # at a glance whether the buyer is fully paid, partially paid, or not
    # paid, without opening each invoice individually.
    # -------------------------------------------------------------------------

    overall_payment_state = fields.Selection([
        ('no_invoices', 'No Invoices'),
        ('not_paid', 'Not Paid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Fully Paid'),
    ], string='Payment Status', compute='_compute_overall_payment_state', store=True)

    @api.depends('installment_ids.invoice_id.payment_state', 'installment_ids.invoice_id.state')
    def _compute_overall_payment_state(self):
        for contract in self:
            invoices = contract.installment_ids.invoice_id.filtered(lambda m: m.state == 'posted')
            if not invoices:
                contract.overall_payment_state = 'no_invoices'
            elif all(inv.payment_state == 'paid' for inv in invoices):
                contract.overall_payment_state = 'paid'
            elif any(inv.payment_state in ('paid', 'partial', 'in_payment') for inv in invoices):
                contract.overall_payment_state = 'partial'
            else:
                contract.overall_payment_state = 'not_paid'

    # -------------------------------------------------------------------------
    # Bulk installment invoicing — one click generates the customer invoice
    # for every pending installment on the contract.
    # -------------------------------------------------------------------------

    def action_generate_installment_invoices(self):
        for contract in self:
            pending_lines = contract.installment_ids.filtered(
                lambda l: not l.invoice_id and l.state != 'cancelled')
            pending_lines._generate_invoices(post=True)
            if pending_lines:
                contract.message_post(
                    body=_('%d installment invoice(s) generated.') % len(pending_lines))
        return True

    # -------------------------------------------------------------------------
    # Cron hook — keeps overdue flag honest without user intervention.
    # Triggered daily. Idempotent: nothing destructive, just refreshes state.
    # -------------------------------------------------------------------------

    @api.model
    def cron_refresh_installment_overdue(self):
        cutoff = fields.Date.subtract(fields.Date.context_today(self), days=0)
        stale = self.env['sale.contract.installment'].search([
            ('state', 'in', ['pending', 'invoiced']),
            ('due_date', '<', cutoff),
        ])
        if stale:
            # Trigger recompute by re-writing an unchanged value
            stale.write({'sequence': lambda l: l.sequence})  # no-op but forces store recompute
        return True

    # -------------------------------------------------------------------------
    # One-click: generate customer invoices for every pending installment
    # on this contract. The installment line state is then auto-derived from
    # the invoice's payment_state (paid / partial / overdue) and the due date.
    # -------------------------------------------------------------------------

    def action_generate_installment_invoices(self):
        for contract in self:
            pending_lines = contract.installment_ids.filtered(
                lambda l: not l.invoice_id and l.state != 'cancelled')
            if not pending_lines:
                continue
            pending_lines._generate_invoices(post=True)
            contract.message_post(
                body=_('%d installment invoice(s) generated.') % len(pending_lines))
        return True

    # -------------------------------------------------------------------------
    # Daily cron — keeps the overdue flag honest for pending/invoiced lines
    # whose due date has passed without an invoice being posted/paid.
    # -------------------------------------------------------------------------

    @api.model
    def cron_refresh_installment_overdue(self):
        today = fields.Date.context_today(self)
        stale = self.env['sale.contract.installment'].search([
            ('state', 'in', ['pending', 'invoiced']),
            ('due_date', '!=', False),
            ('due_date', '<', today),
        ])
        for line in stale:
            line._compute_state()
        return True

    # -------------------------------------------------------------------------
    # One-click: generate vendor bills for every approved commission line on
    # this contract that hasn't been billed yet (one bill per beneficiary).
    # -------------------------------------------------------------------------

    def action_generate_commission_bills(self):
        for contract in self:
            billable = contract.commission_line_ids.filtered(
                lambda l: l.state == 'approved' and not l.bill_id)
            if not billable:
                continue
            bills = billable._generate_bills(post=True)
            contract.message_post(
                body=_('%d commission bill(s) generated for %d line(s).') % (
                    len(bills), len(billable)))
        return True
