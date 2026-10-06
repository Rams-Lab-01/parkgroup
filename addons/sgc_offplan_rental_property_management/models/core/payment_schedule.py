# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from datetime import timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


def _reconcile_plan_rows(rows, basis):
    """Display-only reconciliation of payment-plan rows.

    Generated installments are stored currency-rounded per line and schedule
    percentages are stored with (5, 2) precision - both sources can drift by a
    few cents relative to the Sale Price, so a naive table could show a plan
    that does not add back to the total.

    This is a display-time correction ONLY: the final row keeps the difference
    left after every other row keeps its stored/nominal amount, the final row
    is flagged 'reconciled', and no stored value is touched. The note printed
    under the table documents that the last line carries the rounding residual.
    """
    if not rows or basis is None:
        return rows
    total = Decimal(str(basis or 0.0))
    computed = Decimal(str(sum((r.get('amount') or 0.0) for r in rows)))
    for row in rows:
        row['reconciled'] = False
    last = rows[-1]
    last['amount'] = float(total - (computed - Decimal(str(last.get('amount') or 0.0))))
    if last['amount'] < 0.0:
        last['amount'] = 0.0
    last['reconciled'] = True
    return rows


def _project_plan_rows(schedule, basis, anchor_date):
    """Project a payment.schedule onto a money basis and an anchor date.

    Mirrors the sale.contract installment-generation calendar math (lines are
    anchored to their first due date = anchor + days_after and advanced by
    whole calendar months, booking/one-time lines first per the schedule
    ordering) and returns reconciled rows for report display.

    Each row is a dict:
    {sequence, name, percentage, amount, due_date, state: 'projected'}.
    """
    months_step = {'monthly': 1, 'quarterly': 3, 'bi_annual': 6, 'annual': 12}
    rows = []
    sequence = 1
    for line in schedule.schedule_line_ids.sorted('sequence'):
        n = max(line.number_of_installments, 1)
        step = months_step.get(line.installment_frequency, 0)
        first_due = anchor_date + timedelta(days=line.days_after)
        if n > 1 and step > 0:
            nominal_percent = line.percentage / n
            for i in range(n):
                rows.append({
                    'sequence': sequence,
                    'name': '%s — %d/%d' % (line.name, i + 1, n),
                    'percentage': nominal_percent,
                    'amount': basis * nominal_percent / 100.0,
                    'due_date': first_due + relativedelta(months=step * i),
                    'state': 'projected',
                })
                sequence += 1
        else:
            rows.append({
                'sequence': sequence,
                'name': line.name,
                'percentage': line.percentage,
                'amount': basis * line.percentage / 100.0,
                'due_date': first_due,
                'state': 'projected',
            })
            sequence += 1
    return _reconcile_plan_rows(rows, basis)


class PaymentSchedule(models.Model):
    _name = 'payment.schedule'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _description = 'Payment Schedule Template'
    _order = 'sequence, name'

    # Audit capture scope (Entry 44): schedule identity, contract type and
    # tenant ownership.  total_percentage is computed from the lines (derived
    # noise); description and sequence are display-only.
    _audit_watched_fields = frozenset({
        'name',
        'schedule_type',
        'company_id',
    })
    
    name = fields.Char(string='Schedule Name', required=True, translate=True)
    description = fields.Text(string='Description', translate=True)
    schedule_type = fields.Selection([
        ('sale', 'Sale Contract'),
        ('rental', 'Rental Contract')
    ], string='Schedule Type', required=True, default='sale')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    total_percentage = fields.Float(
        string='Total Percentage',
        compute='_compute_total_percentage',
        store=True,
        help='Must equal 100%'
    )
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    schedule_line_ids = fields.One2many('payment.schedule.line', 'schedule_id',
                                       string='Payment Lines')
    
    @api.depends('schedule_line_ids.percentage')
    def _compute_total_percentage(self):
        for schedule in self:
            schedule.total_percentage = sum(schedule.schedule_line_ids.mapped('percentage'))
    
    def _project_report_rows(self, basis, anchor_date):
        """Project this schedule template onto a money basis and anchor date.

        Used by the Sale reports (offer sheets, booking offers) so a payment
        plan can be shown to a prospect from the selected schedule alone,
        without needing a linked sale.contract.
        """
        self.ensure_one()
        return _project_plan_rows(self, basis, anchor_date)

    @api.constrains('total_percentage')
    def _check_total_percentage(self):
        for schedule in self:
            if abs(schedule.total_percentage - 100.0) > 0.01:  # Allow small rounding difference
                raise ValidationError(_(
                    'Total percentage must equal 100%%. Current total: %.2f%%'
                ) % schedule.total_percentage)


class PaymentScheduleLine(models.Model):
    _name = 'payment.schedule.line'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Payment Schedule Line'
    _order = 'schedule_id, days_after, sequence'

    # Audit capture scope (Entry 44): the financial terms of the line and the
    # schedule that owns it.  sequence is display; note is free internal text.
    _audit_watched_fields = frozenset({
        'schedule_id',
        'name',
        'percentage',
        'days_after',
        'installment_frequency',
        'number_of_installments',
    })

    # Lines are removed as ordinary form editing (editable list, no UI reason
    # workflow); the delete is captured but is not reason-gated (Entry 44).
    _audit_unlink_requires_reason = False
    
    schedule_id = fields.Many2one('payment.schedule', string='Payment Schedule',
                                  required=True, ondelete='cascade')
    name = fields.Char(string='Description', required=True, translate=True,
                      help='e.g., "Booking Payment", "Handover Payment", "Monthly Installment 1"')
    sequence = fields.Integer(string='Sequence', default=10)
    percentage = fields.Float(string='Percentage (%)', required=True, digits=(5, 2),
                             help='Percentage of total amount')
    days_after = fields.Integer(string='Days After Contract', default=0, required=True,
                               help='The FIRST due date of this line = Contract Start Date '
                                    '+ Days. Recurring installments keep that day of month.')
    installment_frequency = fields.Selection([
        ('one_time', 'One Time Payment'),
        ('monthly', 'Monthly (same day each month)'),
        ('quarterly', 'Quarterly (every 3 months, same day)'),
        ('bi_annual', 'Bi-Annual (every 6 months, same day)'),
        ('annual', 'Annual (every 12 months, same day)')
    ], string='Frequency', default='one_time', required=True,
       help='For recurring payments: installments are anchored to the first due '
            'date (Contract Date + Days After Contract) and advance by whole '
            'calendar months, keeping the same day of the month. Short months '
            'use their last day (e.g. 31 Jan -> 28 Feb -> 31 Mar).')
    number_of_installments = fields.Integer(string='Number of Installments', default=1,
                                           help='1 for one-time payment, >1 for split payments')
    note = fields.Text(string='Internal Notes', translate=True)
    
    @api.constrains('percentage')
    def _check_percentage(self):
        for line in self:
            if line.percentage <= 0 or line.percentage > 100:
                raise ValidationError(_('Percentage must be between 0 and 100'))
    
    @api.constrains('days_after')
    def _check_days_after(self):
        for line in self:
            if line.days_after < 0:
                raise ValidationError(_('Days after contract cannot be negative'))
    
    @api.constrains('number_of_installments')
    def _check_installments(self):
        for line in self:
            if line.number_of_installments < 1:
                raise ValidationError(_('Number of installments must be at least 1'))
    
    @api.onchange('installment_frequency')
    def _onchange_installment_frequency(self):
        """Update number of installments based on common patterns"""
        if self.installment_frequency == 'monthly' and self.number_of_installments == 1:
            # Suggest 12 months for annual contract
            self.number_of_installments = 12
        elif self.installment_frequency == 'quarterly' and self.number_of_installments == 1:
            self.number_of_installments = 4
        elif self.installment_frequency == 'bi_annual' and self.number_of_installments == 1:
            self.number_of_installments = 2
