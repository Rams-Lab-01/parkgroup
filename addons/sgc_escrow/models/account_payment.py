# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Payment routing and the escrow policy guard.

Two small, deliberately conservative interventions on the accounting core:

**Routing.** When you press "Register Payment" on a sale-contract invoice whose
project has escrow enabled, the payment wizard opens with the project's escrow
bank journal already selected. This is only a *default* -- the operator can
still choose something else, because sometimes they are right.

**Guard.** The choice is then policed at post time. Configurable three ways:

* ``warn``  (default) -- post a chatter warning on the invoice. Zero risk of
  blocking the finance team on day one, and the evidence accumulates.
* ``block`` -- refuse to post. Use when DLD/RERA compliance is being enforced
  hard.
* ``off``   -- no opinion.

The guard deliberately never *moves* money. It reports, and optionally refuses.

Implementation note (Odoo 19)
---
``account.payment.action_post()`` in Odoo 19 is self-contained -- it flips
``state`` rather than delegating to a ``_post()`` hook (that hook no longer
exists on this model). The guard therefore wraps ``action_post()``, which is
the user-facing commit point and the only place a payment becomes final.

Stated honestly: what this guard is and is not
---
This is a **detective and speed-bump control**, not a hard lock. It identifies
the escrow project through ``reconciled_invoice_ids``, which is derived from
reconciliation. A payment created without any reconciliation behind it has no
invoice to attribute, so it is not policed. Someone determined to route buyer
money around escrow can therefore still do it by hand.

That is a deliberate, documented boundary rather than an oversight. The airtight
control in this module is not the payment policy -- it is the entitlement
ceiling on ``escrow.release``: money cannot leave an escrow account without an
approved document that is mathematically capped by certified progress. This
guard exists to make the *collection* side honest and to surface exceptions
early; the release side is what actually protects the account.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

PAYMENT_POLICY_PARAM = 'sgc_escrow.payment_policy'


class AccountPaymentRegisterEscrowRouting(models.TransientModel):
    """Default the register-payment wizard to the project's escrow journal."""

    _inherit = 'account.payment.register'

    escrow_routing_project_id = fields.Many2one(
        'property.project',
        string='Escrow Project',
        compute='_compute_escrow_routing_project_id',
        help='Set when this payment is being routed into a project escrow account.',
    )

    @api.depends('line_ids.move_id.escrow_project_id')
    def _compute_escrow_routing_project_id(self):
        for wizard in self:
            wizard.escrow_routing_project_id = wizard._escrow_single_project()

    def _escrow_single_project(self):
        """The one escrow-enabled project this wizard batch unambiguously feeds.

        Returns an empty recordset for mixed-project batches, non-sale invoices,
        and projects with escrow off -- every case where this module has no
        business choosing a bank on the user's behalf.
        """
        self.ensure_one()
        projects = self.line_ids.mapped('move_id.escrow_project_id').filtered(
            lambda p: p.escrow_enabled)
        return projects if len(projects) == 1 else self.env['property.project']

    @api.depends(
        'available_journal_ids',  # base trigger -- must be preserved
        'line_ids.move_id.escrow_project_id',
    )
    def _compute_journal_id(self):
        """Prefer the escrow journal of the single escrow-enabled project paid.

        Overriding a compute in Odoo REPLACES its ``@api.depends``: the base
        ``_compute_journal_id`` depends only on ``available_journal_ids``, and
        dropping that would leave the journal default stale whenever the
        available journals change (company switch, payment type change). So the
        base trigger is restated here alongside ours.
        """
        super()._compute_journal_id()

        for wizard in self:
            project = wizard._escrow_single_project()
            journal = project.escrow_bank_journal_id
            if not journal or journal.company_id != wizard.company_id:
                continue
            wizard.journal_id = journal

    @api.depends(
        'payment_type', 'company_id', 'can_edit_wizard',  # base triggers
        'line_ids.move_id.escrow_project_id',
    )
    def _compute_available_journal_ids(self):
        """Keep the escrow journal selectable even without a partner bank account.

        The stock computation derives candidates from the customer's bank
        accounts. A project escrow account is usually held under an escrow agent
        rather than the customer, so without this it would be filtered out of
        the dropdown and the routing default above would be unreachable.

        As with ``_compute_journal_id``, the base triggers are restated because
        an override replaces them rather than extending them.
        """
        super()._compute_available_journal_ids()

        for wizard in self:
            journal = wizard._escrow_single_project().escrow_bank_journal_id
            if journal and journal.company_id == wizard.company_id:
                wizard.available_journal_ids = wizard.available_journal_ids | journal


class AccountPaymentEscrowGuard(models.Model):
    """Refuse (or warn about) buyer money landing outside the escrow account."""

    _inherit = 'account.payment'

    def _escrow_expected_project(self):
        """The single escrow-enabled project this payment is expected to feed."""
        self.ensure_one()
        invoices = self.reconciled_invoice_ids.filtered(
            lambda m: m.move_type in ('out_invoice', 'out_refund'))
        projects = invoices.mapped('escrow_project_id').filtered(
            lambda p: p.escrow_enabled)
        # Only unambiguous, single-project receipts are policed.
        return projects if len(projects) == 1 else self.env['property.project']

    def _escrow_policy_violations(self):
        """Return ``[(payment, project)]`` for receipts booked to the wrong bank.

        Violations are inbound only. Outbound payments (refunds of an
        overpayment, supplier payments) are never policed, because money leaving
        an escrow account legitimately goes to the operating bank.
        """
        violations = []
        for payment in self:
            if payment.payment_type != 'inbound':
                continue
            project = payment._escrow_expected_project()
            if not project:
                continue
            if payment.journal_id == project.escrow_bank_journal_id:
                continue
            violations.append((payment, project))
        return violations

    def _escrow_violation_message(self, payment, project):
        return _(
            'Escrow policy warning: this payment was booked to %(journal)s, but '
            '%(project)s holds escrow and expects %(escrow)s. Money collected from '
            'a buyer of an escrow-enabled project should land in that project\'s '
            'escrow account, so that "collected per unit" and "money in escrow" '
            'stay equal.'
        ) % {
            'journal': payment.journal_id.display_name or _('(none)'),
            'project': project.display_name,
            'escrow': project.escrow_bank_journal_id.display_name,
        }

    def action_post(self):
        """Enforce the configured escrow policy before the payment is posted."""
        policy = self.env['ir.config_parameter'].sudo().get_param(
            PAYMENT_POLICY_PARAM, 'warn')

        if policy != 'off':
            violations = self._escrow_policy_violations()

            if violations and policy == 'block':
                details = [
                    _('Payment %(payment)s of %(amount)s settles a receivable of '
                      '%(project)s, which has escrow enabled. Its journal is '
                      '%(journal)s, not the project escrow account %(escrow)s.') % {
                        'payment': payment.display_name,
                        'amount': payment.amount,
                        'project': project.display_name,
                        'journal': payment.journal_id.display_name or _('(none)'),
                        'escrow': project.escrow_bank_journal_id.display_name,
                    }
                    for payment, project in violations
                ]
                raise UserError(
                    _('Escrow policy: receipts from buyers of an escrow-enabled '
                      'project must be paid into that project\'s escrow account.')
                    + '\n\n' + '\n\n'.join(details))

            if violations and policy == 'warn':
                for payment, project in violations:
                    message = self._escrow_violation_message(payment, project)
                    _logger.warning('sgc_escrow: %s', message)
                    payment.reconciled_invoice_ids.message_post(body=message)

        return super().action_post()