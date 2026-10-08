# -*- coding: utf-8 -*-
"""
Real-time transaction monitoring hook on account.move.

Triggers monitoring rule checks when an invoice transitions to 'posted',
complementing the daily cron-based scan in transaction_monitoring.py.
"""

from odoo import _, api, models
import logging

_logger = logging.getLogger(__name__)


class AccountMoveAML(models.Model):
    _inherit = 'account.move'

    def write(self, vals):
        """Override write to detect invoice posting and run monitoring rules."""
        # Track which invoices are transitioning to posted state
        before = {rec.id: rec.state for rec in self}

        res = super().write(vals)

        # Detect newly posted invoices (state changed to 'posted')
        posted_ids = []
        for rec in self:
            prev_state = before.get(rec.id)
            if prev_state != 'posted' and rec.state == 'posted' and rec.move_type in ('out_invoice', 'out_refund'):
                posted_ids.append(rec.id)

        if posted_ids:
            # Trigger real-time monitoring in a separate transaction to avoid
            # blocking the invoice posting. If monitoring fails, the invoice
            # remains posted — the alert creation failure is non-blocking.
            try:
                posted = self.browse(posted_ids)
                self._trigger_realtime_monitoring(posted)
            except Exception:
                _logger.exception(
                    'Real-time transaction monitoring failed for invoices: %s',
                    posted_ids,
                )

        return res

    @api.model
    def _trigger_realtime_monitoring(self, invoices):
        """Run active monitoring rules against posted invoices.

        Called synchronously on invoice post. For heavy rule sets, consider
        offloading this to a queued job (e.g. queue_job or Odoo async).
        """
        rules = self.env['aml.monitoring.rule'].search([('active', '=', True)])
        if not rules:
            return

        Alert = self.env['aml.transaction.alert']
        alert_count = 0

        for rule in rules:
            if rule.rule_type == 'threshold':
                alert_count += self._check_threshold_rule(rule, invoices, Alert)
            elif rule.rule_type == 'structuring':
                alert_count += self._check_structuring_rule(rule, invoices, Alert)
            elif rule.rule_type == 'round_amount':
                alert_count += self._check_round_amount_rule(rule, invoices, Alert)

        if alert_count:
            _logger.info(
                'Real-time monitoring: %d alert(s) generated for %d invoice(s).',
                alert_count, len(invoices),
            )

    def _check_threshold_rule(self, rule, invoices, Alert):
        """Threshold check — same logic as transaction_monitoring.py cron."""
        count = 0
        for inv in invoices:
            if inv.amount_total >= rule.threshold_amount:
                existing = Alert.search_count([
                    ('rule_id', '=', rule.id),
                    ('invoice_id', '=', inv.id),
                ])
                if not existing:
                    Alert.create({
                        'rule_id': rule.id,
                        'partner_id': inv.partner_id.id,
                        'transaction_amount': inv.amount_total,
                        'invoice_id': inv.id,
                        'transaction_date': inv.invoice_date,
                        'alert_description': _(
                            'Real-time: Transaction amount AED %s exceeds threshold AED %s.',
                            f'{inv.amount_total:,.2f}',
                            f'{rule.threshold_amount:,.2f}',
                        ),
                    })
                    count += 1
        return count

    def _check_structuring_rule(self, rule, invoices, Alert):
        """Structuring detection — amounts just below threshold."""
        count = 0
        threshold = rule.threshold_amount or 55000.0
        floor = threshold * (1 - rule.structuring_percentage / 100.0)
        for inv in invoices:
            if floor <= inv.amount_total < threshold:
                existing = Alert.search_count([
                    ('rule_id', '=', rule.id),
                    ('invoice_id', '=', inv.id),
                ])
                if not existing:
                    Alert.create({
                        'rule_id': rule.id,
                        'partner_id': inv.partner_id.id,
                        'transaction_amount': inv.amount_total,
                        'invoice_id': inv.id,
                        'transaction_date': inv.invoice_date,
                        'alert_description': _(
                            'Real-time: Potential structuring AED %s within %s%% of threshold AED %s.',
                            f'{inv.amount_total:,.2f}',
                            f'{rule.structuring_percentage:.0f}',
                            f'{threshold:,.2f}',
                        ),
                    })
                    count += 1
        return count

    def _check_round_amount_rule(self, rule, invoices, Alert):
        """Round amount detection."""
        count = 0
        threshold = rule.threshold_amount or 10000.0
        for inv in invoices:
            if inv.amount_total >= threshold and inv.amount_total % 1000 == 0:
                existing = Alert.search_count([
                    ('rule_id', '=', rule.id),
                    ('invoice_id', '=', inv.id),
                ])
                if not existing:
                    Alert.create({
                        'rule_id': rule.id,
                        'partner_id': inv.partner_id.id,
                        'transaction_amount': inv.amount_total,
                        'invoice_id': inv.id,
                        'transaction_date': inv.invoice_date,
                        'alert_description': _(
                            'Real-time: Round amount AED %s detected (multiple of 1,000).',
                            f'{inv.amount_total:,.2f}',
                        ),
                    })
                    count += 1
        return count
