# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import logging

_logger = logging.getLogger(__name__)
from markupsafe import Markup, escape
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
    cancel_reason = fields.Text(
        string='Sale Cancellation Reason', readonly=True, copy=False, tracking=True,
    )
    state = fields.Selection([
        ('draft', 'Draft'),
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
        help="How much has actually been received against this unit so far, "
             "whatever stage the contract is in. Partly paid instalments count.",
    )
    total_paid_fees = fields.Monetary(
        string='of which Fees',
        currency_field='currency_id',
        compute='_compute_total_paid_fees',
        store=True,
        help='DLD, admin, registration and Oqood charges settled on top of the '
             'sale price. Part of Total Paid, shown apart so a unit that is '
             'fully paid does not read as over-paid.',
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
    collection_pct_ratio = fields.Float(
        string='Collection %',
        compute='_compute_collection_pct_ratio',
        digits=(5, 2),
        help='Same as Collection % but expressed as a 0..1 ratio so the '
             'percentage widget renders an exact figure with the %% sign.',
    )
    last_payment_date = fields.Date(
        string='Last Payment Date',
        compute='_compute_last_payment_date',
        help='Most recent date a payment was actually received against this '
             'contract (reconciled payment / paid installment).',
    )

    @api.depends('collection_pct')
    def _compute_collection_pct_ratio(self):
        for contract in self:
            contract.collection_pct_ratio = (contract.collection_pct or 0.0) / 100.0

    @api.depends('installment_ids.invoice_id.payment_state',
                 'installment_ids.invoice_id.state',
                 'installment_ids.state',
                 'installment_ids.due_date',
                 'contract_date')
    def _compute_last_payment_date(self):
        for contract in self:
            dates = []
            for line in contract.installment_ids:
                inv = line.invoice_id
                if not inv or inv.state != 'posted':
                    continue
                if inv.payment_state in ('paid', 'in_payment', 'partial'):
                    ref = inv.invoice_date or line.due_date
                    if ref:
                        dates.append(ref)
            contract.last_payment_date = max(dates) if dates else False
    last_activity_date = fields.Date(
        string='Last Activity Date',
        compute='_compute_last_activity_date',
        store=True,
        help='Most recent payment date on paid installments; falls back to the '
             'contract date. Used by the dashboard aging buckets.',
    )

    @api.depends('sale_price', 'total_paid', 'total_paid_fees')
    def _compute_collection_metrics(self):
        for contract in self:
            sale = contract.sale_price or 0.0
            # Fees are cash the buyer owes on top of the price: they are part of
            # Total Paid but they are not price, so they never make a unit look
            # over-paid or under-collected.
            paid = (contract.total_paid or 0.0) - (contract.total_paid_fees or 0.0)
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

    def _sgc_received_amount(self):
        """The money actually received against this contract's unit.

        The receipts are the truth: an instalment that is only partly paid is
        still money in the bank, and money can arrive before the invoice is
        raised. When the unit carries no receipt (a sale that never started),
        what is settled on the contract's own invoices is the fallback.
        """
        self.ensure_one()
        helper = self.env.get('sgc.eoi.receipt.helper')
        if helper is not None and self.property_id:
            received = helper._received_for_unit(self.property_id)
            if received:
                return received
        invoices = self.installment_ids.filtered(
            lambda line: line.invoice_id and line.invoice_id.state == 'posted').mapped('invoice_id')
        return sum(invoices.mapped('amount_total')) - sum(invoices.mapped('amount_residual'))

    # Invoices that are fees charged on top of the sale price, not the price.
    FEE_REF_KEYWORDS = (
        'admin fee', 'dld', 'oqood', 'rak fee', 'registration fee',
        'transfer fee', 'title deed', 'stamp duty', 'reservation fee',
    )

    def _sgc_unit_invoices(self):
        """The posted customer invoices raised against this contract's unit.

        Both links count: the invoice's own unit, and the invoices carried by
        the unit's contracts (a legacy invoice can carry the contract but not
        the unit).
        """
        self.ensure_one()
        Move = self.env['account.move'].sudo()
        unit = self.property_id
        if not unit:
            return Move.browse()
        contracts = self.sudo().search([('property_id', '=', unit.id)])
        return Move.search([
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            '|',
            ('property_id', '=', unit.id),
            ('sold_id', 'in', contracts.ids),
        ])

    @api.model
    def _sgc_is_fee_move(self, move):
        """A fee invoice: DLD, admin, registration, Oqood - not the price."""
        ref = (move.ref or '').lower()
        return any(keyword in ref for keyword in self.FEE_REF_KEYWORDS)

    def _sgc_settled_amount(self):
        """The money actually settled against this unit's invoices.

        Receipts count by what they settled, not by their face value: a receipt
        that never reached this unit's invoices, or that only partly reached
        them, is not money against this sale. A unit with no invoice yet (an
        EOI-stage sale) falls back to the receipts registered against it.
        """
        self.ensure_one()
        invoices = self._sgc_unit_invoices()
        settled = sum(invoices.mapped('amount_total')) - sum(invoices.mapped('amount_residual'))
        if settled:
            return settled
        return self._sgc_received_amount()

    @api.depends('property_id',
                 'installment_ids.amount',
                 'installment_ids.state',
                 'installment_ids.invoice_id.state',
                 'installment_ids.invoice_id.amount_residual')
    def _compute_total_paid(self):
        for contract in self:
            contract.total_paid = contract._sgc_settled_amount()

    def _compute_total_paid_fees(self):
        for contract in self:
            fees = contract._sgc_unit_invoices().filtered(
                lambda move: contract._sgc_is_fee_move(move))
            contract.total_paid_fees = (
                sum(fees.mapped('amount_total')) - sum(fees.mapped('amount_residual')))

    # ------------------------------------------------------------------
    # Unit payment monitoring: payment plan vs collection, per contract.
    # Stored so the monitor list can filter and sort; the due-date boundary
    # is date-sensitive, so a daily cron refreshes these values.
    # ------------------------------------------------------------------
    plan_total = fields.Monetary(
        string='Plan Total', currency_field='currency_id',
        compute='_compute_payment_monitor', store=True)
    plan_due_to_date = fields.Monetary(
        string='Due To Date', currency_field='currency_id',
        compute='_compute_payment_monitor', store=True)
    plan_collected = fields.Monetary(
        string='Collected', currency_field='currency_id',
        compute='_compute_payment_monitor', store=True)
    plan_outstanding = fields.Monetary(
        string='Outstanding', currency_field='currency_id',
        compute='_compute_payment_monitor', store=True)
    plan_overdue_amount = fields.Monetary(
        string='Overdue Amount', currency_field='currency_id',
        compute='_compute_payment_monitor', store=True)
    plan_overdue_count = fields.Integer(
        string='Overdue Instalments',
        compute='_compute_payment_monitor', store=True)
    plan_first_missed_date = fields.Date(
        string='First Missed',
        compute='_compute_payment_monitor', store=True)
    payment_monitor_status = fields.Selection([
        ('no_plan', 'No Plan'),
        ('settled', 'Settled'),
        ('advance', 'Advance'),
        ('on_track', 'On Track'),
        ('underpaid', 'Underpaid'),
        ('overdue', 'Overdue'),
    ], string='Plan Status',
        compute='_compute_payment_monitor', store=True)

    @api.depends('installment_ids.amount', 'installment_ids.due_date',
                 'installment_ids.state',
                 'installment_ids.invoice_id.state',
                 'installment_ids.invoice_id.amount_total',
                 'installment_ids.invoice_id.amount_residual')
    def _compute_payment_monitor(self):
        today = fields.Date.context_today(self)
        for contract in self:
            lines = contract.installment_ids.filtered(
                lambda l: l.state != 'cancelled')
            plan_total = sum(lines.mapped('amount'))
            due_to_date = collected = overdue_amount = 0.0
            overdue_count = 0
            first_missed = False
            for line in lines:
                amt = line.amount or 0.0
                paid = 0.0
                inv = line.invoice_id
                if inv and inv.state == 'posted':
                    paid = min(max(amt - (inv.amount_residual or 0.0), 0.0), amt)
                collected += paid
                if line.due_date and line.due_date <= today:
                    due_to_date += amt
                    if paid + 0.005 < amt:
                        overdue_amount += amt - paid
                        overdue_count += 1
                        if not first_missed or line.due_date < first_missed:
                            first_missed = line.due_date
            outstanding = plan_total - collected
            contract.plan_total = plan_total
            contract.plan_due_to_date = due_to_date
            contract.plan_collected = collected
            contract.plan_outstanding = outstanding
            contract.plan_overdue_amount = overdue_amount
            contract.plan_overdue_count = overdue_count
            contract.plan_first_missed_date = first_missed or False
            if not lines:
                status = 'no_plan'
            elif outstanding <= 0.005:
                status = 'settled'
            elif collected > due_to_date + 0.005:
                status = 'advance'
            elif overdue_count:
                status = 'overdue'
            elif collected + 0.005 < due_to_date:
                status = 'underpaid'
            else:
                status = 'on_track'
            contract.payment_monitor_status = status

    def _cron_refresh_payment_monitor(self):
        # Daily refresh of the date-sensitive fields. Stored computes re-run only when their inputs
        # change, never when a date passes: an installment invoiced before its due date stayed
        # 'Invoiced' after it fell due unpaid, while the contract already said 'Behind Schedule'.
        today = fields.Date.context_today(self)
        self.env['sale.contract.installment'].search(
            [('due_date', '<', today), ('state', 'in', ('pending', 'invoiced'))])._compute_state()
        contracts = self.search([])
        contracts._compute_overall_payment_state()
        contracts._compute_payment_monitor()
        # Total Paid follows the money, and money moves without touching an
        # installment: a receipt posted against the unit, or a reconciliation
        # between two invoices, leaves the stored total where it was.
        contracts._compute_total_paid()
        contracts._compute_total_paid_fees()
        return True

    @api.model
    def _cron_generate_eligible_commission_bills(self):
        """Weekly: raise DRAFT invoices for approved, unbilled commission lines
        on contracts that meet the eligibility criteria.

        Draft only - Finance reviews and posts them. Once raised, neither the
        line nor the invoice can be reset or deleted (guards on
        property.commission.line and account.move), so the audit trail stays
        intact. Disable with the config parameter
        sgc_offplan_rental_property_management.commission_auto_draft_bills = 0.
        """
        params = self.env['ir.config_parameter'].sudo()
        if params.get_param(
                'sgc_offplan_rental_property_management.commission_auto_draft_bills',
                '1') not in ('1', 'True', 'true'):
            _logger.info('Commission auto-billing is disabled by configuration.')
            return True
        created = 0
        contracts = self.search([('commission_line_ids', '!=', False)])
        for contract in contracts:
            lines = contract.commission_line_ids.filtered(
                lambda l: l.state == 'approved' and not l.bill_id and l.partner_id)
            if not lines or not contract.is_commission_eligible:
                continue
            try:
                with self.env.cr.savepoint():
                    moves = lines._generate_bills(post=False)
                    if moves:
                        lines.write({'auto_generated': True})
                        created += len(moves)
                        _logger.info(
                            'Commission auto-billing: %s draft invoice(s) for %s',
                            len(moves), contract.display_name)
            except (UserError, ValidationError) as exc:
                _logger.warning(
                    'Commission auto-billing skipped for %s: %s',
                    contract.display_name, exc)
        _logger.info(
            'Commission auto-billing run finished: %s draft invoice(s).', created)
        return True

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

    def action_cancel(self):
        """Direct cancel (programmatic). The UI uses ``action_cancel_reason``."""
        return self._apply_cancellation(None, 'cancelled')

    def action_cancel_reason(self):
        """Open the governed-cancel wizard (an operator reason is mandatory)."""
        self.ensure_one()
        if self.state in ('cancelled', 'refunded'):
            raise UserError(_('This contract is already %s.', self.state))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cancel Sale Contract'),
            'res_model': 'sale.contract.cancel.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref(
                'sgc_offplan_rental_property_management.sale_contract_cancel_wizard_form'
            ).id,
            'target': 'new',
            'context': {
                'default_contract_id': self.id,
                'default_new_state': 'cancelled',
            },
        }

    def _apply_cancellation(self, reason, new_state='cancelled'):
        """Single executor for every sale-contract cancellation.

        Logs ``reason`` on the chatter BEFORE changing the status (the ordering
        the business requires), then moves the contract to ``new_state`` and
        releases the linked unit. Called by the wizard (reason required) and by
        the legacy direct ``action_cancel`` (no reason).
        """
        valid_states = dict(self._fields['state'].selection)
        if new_state not in valid_states:
            raise UserError(_('Unsupported cancellation outcome: %s.', new_state))
        for contract in self:
            if contract.state in ('cancelled', 'refunded'):
                raise UserError(_('%s is already %s.', contract.name, contract.state))
            if reason:
                body = Markup('<b>Cancellation reason:</b><br/>') + escape(reason)
            else:
                body = (Markup('Contract status set to %s.')
                        % escape(valid_states.get(new_state, new_state)))
            # Log first, then change state (business ordering).
            contract.message_post(body=body)
            vals = {'state': new_state}
            if reason:
                vals['cancel_reason'] = reason
            contract.write(vals)
            if contract.property_id:
                contract.property_id.write({'state': 'available'})
        return True

    def action_draft(self):
        for contract in self:
            if contract.state not in (
                    'eoi', 'booked', 'confirmed', 'spa_issued', 'spa_signed',
                    'certificate_issued', 'in_progress', 'handover',
                    'cancelled'):
                raise UserError(_(
                    'Only contracts in an active or cancelled stage can be '
                    'set back to draft.'))
            contract.state = 'draft'

    # -------------------------------------------------------------------------
    # Installment generation
    # -------------------------------------------------------------------------

    @api.constrains('sale_price')
    def _check_sale_price_covers_plan(self):
        self._check_installments_within_price()

    def _check_installments_within_price(self):
        """The installments of a contract may never add up to more than its sale price."""
        for contract in self:
            total = sum(contract.installment_ids.filtered(lambda l: l.state != 'cancelled').mapped('amount'))
            if total > (contract.sale_price or 0.0) + 1.0:   # ponytail: AED 1 absorbs template rounding (0.19 seen on an 87-line plan)
                raise ValidationError(_(
                    'The installments of %(contract)s add up to %(total)s, more than the sale price %(price)s. '
                    'Remove or reduce installments first (invoiced installments stay; generating a payment schedule '
                    'adds the full plan on top of them).',
                    contract=contract.display_name, total='{:,.2f}'.format(total), price='{:,.2f}'.format(contract.sale_price or 0.0)))

    def action_generate_installments(self):
        """Generate installment lines from the linked payment schedule template."""
        self.ensure_one()
        if not self.payment_schedule_id:
            raise UserError(_('Please select a Payment Schedule before generating installments.'))
        if not self.contract_date:
            raise UserError(_('Please set a Contract Date before generating installments.'))

        # Replace every installment that has no live invoice. Was: only state 'pending', so an
        # uninvoiced line already past due ('overdue') survived and the plan was doubled.
        draft_lines = self.installment_ids.filtered(lambda l: not l.invoice_id or l.invoice_id.state == 'cancel')
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
    # Payments smart button (money actually received against the invoices)
    # -------------------------------------------------------------------------

    payment_ids = fields.Many2many(
        'account.payment',
        compute='_compute_payment_ids',
        string='Payments',
    )
    payment_count = fields.Integer(
        string='Payment Count',
        compute='_compute_payment_ids',
    )
    payment_total = fields.Monetary(
        string='Collected via Payments',
        currency_field='currency_id',
        compute='_compute_payment_ids',
        help='Sum of the posted payments reconciled to this contract\'s '
             'invoices, in the contract currency.',
    )

    @api.depends('invoice_ids')
    def _compute_payment_ids(self):
        Payment = self.env['account.payment']
        # Odoo 17+ links payments to invoices via reconciled_invoice_ids; the
        # older invoice_ids field was removed. Support both so the button keeps
        # working across upgrades.
        link_field = next(
            (f for f in ('reconciled_invoice_ids', 'invoice_ids')
             if f in Payment._fields), None)
        for contract in self:
            payments = Payment
            invoices = contract.invoice_ids
            if invoices and link_field:
                payments = Payment.search([
                    (link_field, 'in', invoices.ids),
                    ('state', '!=', 'draft'),
                ])
            contract.payment_ids = payments
            contract.payment_count = len(payments)
            contract.payment_total = sum(payments.mapped('amount'))

    def action_view_payments(self):
        self.ensure_one()
        return {
            'name': _('Payments'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.payment_ids.ids)],
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
        ('no_plan', 'No Plan'),
        ('settled', 'Fully Paid'),
        ('advance', 'Advance Paid'),
        ('on_track', 'On Track'),
        ('behind', 'Behind Schedule'),
    ], string='Payment Status', compute='_compute_overall_payment_state', store=True)

    @api.depends('installment_ids.amount',
                 'installment_ids.due_date',
                 'installment_ids.state',
                 'installment_ids.invoice_id.state',
                 'installment_ids.invoice_id.amount_total',
                 'installment_ids.invoice_id.amount_residual',
                 'sale_price')
    def _compute_overall_payment_state(self):
        """Schedule performance: is this buyer behind, on track, or ahead?

        The label answers the only question that matters day to day - has the
        buyer paid what the plan says is due so far?

          Fully Paid      - nothing left to collect on the whole plan
          Advance Paid   - collected more than the plan has fallen due
          On Track       - collected at least what has fallen due
          Behind Schedule- collected less than has fallen due
          No Plan        - the contract has no installment schedule

        Deliberately NOT derived from which invoices happen to exist: a
        contract with a valid plan and no overdue installment is 'On Track'
        even when its future invoices have not been raised yet.
        """
        today = fields.Date.context_today(self)
        for contract in self:
            lines = contract.installment_ids.filtered(lambda l: l.state != 'cancelled')
            if not lines:
                contract.overall_payment_state = 'no_plan'
                continue

            collected = due_to_date = 0.0
            for line in lines:
                amount = line.amount or 0.0
                inv = line.invoice_id
                paid = 0.0
                if inv and inv.state == 'posted':
                    paid = min(max(amount - (inv.amount_residual or 0.0), 0.0), amount)
                collected += paid
                if line.due_date and line.due_date <= today:
                    due_to_date += amount

            plan_total = sum(lines.mapped('amount'))
            outstanding = plan_total - collected
            # "Fully Paid" must mean the buyer owes nothing at all. A plan that
            # was generated for less than the sale price (under-planned
            # contract) can be fully collected while a large balance remains,
            # so the sale price - not the plan - is the final authority.
            sale_outstanding = (contract.sale_price or 0.0) - collected
            if sale_outstanding <= 0.01:
                state = 'settled'
            elif collected > due_to_date + 0.01:
                state = 'advance'
            elif collected + 0.01 >= due_to_date:
                state = 'on_track'
            else:
                state = 'behind'
            contract.overall_payment_state = state


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

    # -------------------------------------------------------------------------
    # Project-bound SPA template resolution
    # -------------------------------------------------------------------------

    def _get_spa_agreement_template_html(self):
        """Return the rendered HTML of the project-bound agreement template
        for this contract, or an empty string when no template applies.

        Called from the SPA QWeb report template so that projects with a
        dedicated SPA *agreement template* (a record on ``agreement.template``
        tagged with ``model == 'sale.contract'`` and linked to a project)
        can render their custom clauses instead of the hardcoded template.
        """
        self.ensure_one()
        AgreementTemplate = self.env['agreement.template']
        from markupsafe import Markup
        return Markup(AgreementTemplate._resolve_contract_template(self) or '')
