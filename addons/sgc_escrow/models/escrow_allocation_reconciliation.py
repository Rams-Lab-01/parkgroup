# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Reconciliation of the allocation register against the accounting ledger.

The register currently holds *source* figures: what a bank confirmation or the
escrow agent's allocation report said about each unit. Accounting entries for
historic invoices and receipts are deferred, so at this moment the ledger side
of every row is legitimately zero.

This module file wires up the reconciliation so that the moment those entries
exist, answering "does the accounting agree with the allocation?" is a click, not
a project:

* ``ledger_invoiced_amount``    -- posted customer invoices raised for the unit
* ``ledger_received_amount``    -- payments settled against those invoices
* ``ledger_received_in_escrow`` -- of those, the part that reached the project's
                                   escrow bank account
* ``reconciliation_state``      -- no source / pending / matched / variance
* ``reconciliation_variance``   -- allocated (source) less received into escrow

Nothing here creates, moves or posts anything. The sign-off fields
(``reconciled``, ``reconciled_on``, ``reconciled_by``, ``reconciliation_note``)
are a finance decision recorded against the register.

Computes are written batch-first: one search for invoices and one for payments
across the whole recordset, then aggregation in Python. Row-at-a-time searching
would issue ~450 queries to open a 226-row register.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Tolerance, in company currency, below which a difference is rounding rather
# than a genuine reconciliation break.
RECONCILIATION_TOLERANCE = 1.0


class EscrowAllocationReconciliation(models.Model):
    _inherit = 'escrow.allocation'

    # -- Ledger side (read-only; never written by this module) ---
    ledger_invoiced_amount = fields.Monetary(
        string='Invoiced (Accounting)',
        currency_field='currency_id',
        compute='_compute_ledger_totals',
        help='Posted customer invoices raised for this unit, from the general '
             'ledger. Zero while historic invoicing is still deferred.',
    )
    ledger_received_amount = fields.Monetary(
        string='Receipts (Accounting)',
        currency_field='currency_id',
        compute='_compute_ledger_totals',
        help='Payments settled against this unit\'s invoices, whatever bank they '
             'landed in.',
    )
    ledger_received_in_escrow = fields.Monetary(
        string='Received into Escrow (Accounting)',
        currency_field='currency_id',
        compute='_compute_ledger_totals',
        help='Of those receipts, the portion paid into this project\'s escrow bank '
             'account. This is the figure that should agree with "Allocated to '
             'Escrow (source)".',
    )
    ledger_open_amount = fields.Monetary(
        string='Still Outstanding (Accounting)',
        currency_field='currency_id',
        compute='_compute_ledger_totals',
        help='Invoiced less received. Expected until the payment plan runs its course.',
    )

    # -- Reconciliation verdict ---
    # Non-stored on purpose: these depend on the non-stored ledger amounts
    # above, and a stored computed field may not depend on a non-stored one.
    reconciliation_state = fields.Selection(
        [
            ('no_source', 'No Source Figure'),
            ('no_ledger', 'Awaiting Accounting Entries'),
            ('matched', 'Matched'),
            ('variance', 'Variance'),
        ],
        string='Reconciliation',
        compute='_compute_reconciliation',
        help='Whether the source allocation and the accounting ledger agree. '
             '"Awaiting Accounting Entries" is the expected state until the '
             'deferred invoice and receipt entries are created.',
    )
    reconciliation_variance = fields.Monetary(
        string='Reconciliation Variance',
        currency_field='currency_id',
        compute='_compute_reconciliation',
        help='Allocated to escrow (source) less received into escrow (accounting).',
    )

    # -- Finance sign-off ---
    reconciled = fields.Boolean(
        string='Signed Off',
        help='Set by finance once the source allocation and the accounting ledger '
             'agree for this unit, or once any residual difference is explained in '
             'the note.',
    )
    reconciled_on = fields.Datetime(
        string='Signed Off On',
        copy=False,
    )
    reconciled_by = fields.Many2one(
        'res.users',
        string='Signed Off By',
        copy=False,
    )
    # ``reconciliation_note`` is declared once, on the base model in
    # escrow_allocation.py -- it serves both the source flags and this sign-off.

    # -- Computes ---
    @api.depends_context('company')
    def _compute_ledger_totals(self):
        """Batch-read the ledger for every row in one pass.

        Two searches total, regardless of recordset size: one for the posted
        customer invoices touching these units, one for the payments that
        settled them.
        """
        allocations = self
        invoiced = {a.id: 0.0 for a in allocations}
        received = {a.id: 0.0 for a in allocations}
        in_escrow = {a.id: 0.0 for a in allocations}

        contracts = allocations.mapped('contract_id')
        units = allocations.mapped('unit_id')
        if not contracts and not units:
            for allocation in allocations:
                allocation._set_ledger_values(0.0, 0.0, 0.0)
            return

        domain = [
            ('move_type', '=', 'out_invoice'),
            ('state', '=', 'posted'),
            '|',
            ('sold_id', 'in', contracts.ids),
            ('sold_property_id', 'in', units.ids),
        ]
        invoices = self.env['account.move'].search(domain)
        if not invoices:
            for allocation in allocations:
                allocation._set_ledger_values(0.0, 0.0, 0.0)
            return

        # Which escrow journal each project's receipts must have landed in.
        escrow_journals = {}
        for project in allocations.mapped('project_id'):
            journal = project.escrow_bank_journal_id
            if journal:
                escrow_journals[project.id] = journal.id

        invoice_by_unit = {}
        invoice_by_contract = {}
        for invoice in invoices:
            if invoice.sold_property_id:
                invoice_by_unit.setdefault(invoice.sold_property_id.id, []).append(invoice)
            if invoice.sold_id:
                invoice_by_contract.setdefault(invoice.sold_id.id, []).append(invoice)

        payments_by_invoice = {}
        for invoice in invoices:
            # Reconciled Payments is the documented link from an invoice to the
            # payments that settled it (account: matched/reconciled payment ids).
            payments = invoice.reconciled_payment_ids
            if payments:
                payments_by_invoice[invoice.id] = payments

        for allocation in allocations:
            unit_invoices = list(invoice_by_unit.get(allocation.unit_id.id, []))
            for invoice in invoice_by_contract.get(allocation.contract_id.id, []):
                if invoice not in unit_invoices:
                    unit_invoices.append(invoice)

            invoiced_total = 0.0
            received_total = 0.0
            escrow_total = 0.0
            journal_id = escrow_journals.get(allocation.project_id.id)

            for invoice in unit_invoices:
                invoiced_total += invoice.amount_total
                for payment in payments_by_invoice.get(invoice.id, []):
                    amount = abs(payment.amount)
                    received_total += amount
                    if journal_id and payment.journal_id.id == journal_id:
                        escrow_total += amount

            invoiced[allocation.id] = invoiced_total
            received[allocation.id] = received_total
            in_escrow[allocation.id] = escrow_total
            allocation._set_ledger_values(
                invoiced_total, received_total, escrow_total)

    def _set_ledger_values(self, invoiced, received, in_escrow):
        """Assign the three ledger amounts plus the derived outstanding figure."""
        self.ledger_invoiced_amount = invoiced
        self.ledger_received_amount = received
        self.ledger_received_in_escrow = in_escrow
        self.ledger_open_amount = invoiced - received

    @api.depends(
        'allocated_amount', 'has_source_data', 'ledger_received_in_escrow',
        'ledger_invoiced_amount',
    )
    def _compute_reconciliation(self):
        for allocation in self:
            if not allocation.has_source_data:
                # No figure from the source -- nothing to reconcile against yet.
                allocation.reconciliation_state = 'no_source'
                allocation.reconciliation_variance = 0.0
                continue

            ledger_has_entries = bool(
                allocation.ledger_invoiced_amount
                or allocation.ledger_received_in_escrow)

            if not ledger_has_entries:
                # The expected state while accounting entries are deferred.
                allocation.reconciliation_state = 'no_ledger'
                allocation.reconciliation_variance = 0.0
                continue

            variance = allocation.allocated_amount - allocation.ledger_received_in_escrow
            allocation.reconciliation_variance = variance
            allocation.reconciliation_state = (
                'matched' if abs(variance) <= RECONCILIATION_TOLERANCE
                else 'variance')

    # -- Actions ---
    def action_sign_off(self):
        """Record finance's acceptance of this unit's allocation.

        Records who signed off and when. Deliberately does *not* touch the
        ledger: signing off says "the source figure and the accounting agree, or
        the difference is explained", nothing more.
        """
        for allocation in self:
            if allocation.reconciliation_state == 'no_source':
                raise UserError(_(
                    'Cannot sign off %s: the source carried no escrow allocation '
                    'figure for this unit, so there is nothing to reconcile.'
                ) % allocation.display_name)
            if allocation.reconciliation_state == 'no_ledger':
                raise UserError(_(
                    'Cannot sign off %s yet: it has no accounting entries to '
                    'reconcile against. Create the invoice and receipt entries '
                    'first, then come back to this unit.'
                ) % allocation.display_name)
            if not (allocation.reconciliation_note or '').strip():
                raise UserError(_(
                    'Signing off %s requires a reconciliation note: cite the '
                    'document the allocation was read from and explain any '
                    'residual difference.'
                ) % allocation.display_name)
            allocation.write({
                'reconciled': True,
                'reconciled_on': fields.Datetime.now(),
                'reconciled_by': self.env.user.id,
            })
        return True

    def action_clear_sign_off(self):
        for allocation in self:
            allocation.write({
                'reconciled': False,
                'reconciled_on': False,
                'reconciled_by': False,
            })
        return True

    def action_view_invoices(self):
        """Open this unit's accounting invoices, to check the entries by hand."""
        self.ensure_one()
        domain = [('move_type', '=', 'out_invoice'), ('state', '=', 'posted')]
        if self.contract_id:
            domain += [('|', ('sold_id', '=', self.contract_id.id),
                        ('sold_property_id', '=', self.unit_id.id))]
        else:
            domain += [('sold_property_id', '=', self.unit_id.id)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices - %s') % self.unit_id.display_name,
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': domain,
        }

    def action_view_project_statement(self):
        """The bank/auditor document covering this unit's project."""
        self.ensure_one()
        return self.env.ref(
            'sgc_escrow.action_report_escrow_project_statement'
        ).report_action(self.project_id)
