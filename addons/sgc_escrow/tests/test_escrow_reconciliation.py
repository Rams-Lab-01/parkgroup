# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Accounting entries are deferred: the allocation register stands alone.

Two things are pinned here, and they are the whole point of this module's
current phase:

1. Posting a release is refused while ``sgc_escrow.posting_enabled`` is off,
   so no journal entry can be created by accident.
2. The allocation register reconciles correctly once invoice and receipt
   entries *do* exist -- which is the state the business will be in next.

Nothing in the module creates accounting entries during import or sign-off.
"""

from odoo.exceptions import UserError

from .common import EscrowCommon


class TestEscrowPostingDeferred(EscrowCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.param = cls.env['ir.config_parameter'].sudo()
        cls._original = cls.param.get_param('sgc_escrow.posting_enabled')

    def setUp(self):
        super().setUp()
        self.project = self.setup_project(code='SGCPD')
        self.unit = self.create_unit(self.project, '101')
        self.buyer = self.create_partner('SGCEscrow Deferred Buyer')
        self.contract = self.create_contract(self.unit, self.buyer)
        self.invoice = self.create_invoice(self.contract, 1000000.0)
        # Deferred by default: this is the shipped state.
        self.param.set_param('sgc_escrow.posting_enabled', 'False')

    def tearDown(self):
        self.param.set_param('sgc_escrow.posting_enabled', self._original or False)
        super().tearDown()

    def test_posting_is_refused_while_deferred(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)

        release = self.create_release(self.project, amount=100000.0)
        # Bypass the entitlement gate on purpose: we are testing the *posting*
        # gate, so the release must be approvable and only then refused.
        release._write_controlled({'is_override': True,
                                   'override_reason': 'test fixture'})
        manager = self._escrow_manager()
        release.with_user(manager).action_approve()
        self.assertEqual(release.state, 'approved')

        with self.assertRaises(UserError) as caught:
            release.with_user(manager).action_post()
        self.assertIn('disabled', str(caught.exception).lower())

    def test_no_journal_entry_is_created_while_deferred(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        before = self.env['account.move'].search_count(
            [('journal_id', '=', self.project.escrow_bank_journal_id.id)])

        release = self.create_release(self.project, amount=100000.0)
        release._write_controlled({'is_override': True,
                                   'override_reason': 'test fixture'})
        manager = self._escrow_manager()
        release.with_user(manager).action_approve()
        with self.assertRaises(UserError):
            release.with_user(manager).action_post()

        after = self.env['account.move'].search_count(
            [('journal_id', '=', self.project.escrow_bank_journal_id.id)])
        self.assertEqual(before, after,
                         'A refused post must not leave an entry behind.')
        self.assertFalse(release.journal_entry_id)

    def test_posting_still_works_once_explicitly_enabled(self):
        self.param.set_param('sgc_escrow.posting_enabled', 'True')
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)

        release = self.create_release(self.project, amount=100000.0)
        release.action_approve()
        release.action_post()
        self.assertEqual(release.state, 'posted')
        self.assertTrue(release.journal_entry_id)


class TestEscrowAllocationReconciliation(EscrowCommon):
    """The register reconciles cleanly against entries that exist."""

    def setUp(self):
        super().setUp()
        self.project = self.setup_project(code='SGCRC')
        self.unit = self.create_unit(self.project, '101')
        self.buyer = self.create_partner('SGCEscrow Recon Buyer')
        self.contract = self.create_contract(self.unit, self.buyer)

    def _allocation(self, allocated, unit=None, contract=None):
        return self.env['escrow.allocation'].create({
            'project_id': self.project.id,
            'unit_id': (unit or self.unit).id,
            'contract_id': (contract or self.contract).id,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'sale_price_snapshot': 1000000.0,
            'escrow_pct': 20.0,
            'allocated_amount': allocated,
            'source_reference': 'test',
        })

    # -- Before accounting entries exist ---
    def test_without_ledger_entries_the_state_is_pending_not_matched(self):
        allocation = self._allocation(200000.0)
        self.assertEqual(allocation.reconciliation_state, 'no_ledger')
        self.assertAlmostEqual(allocation.ledger_invoiced_amount, 0.0, places=2)
        self.assertAlmostEqual(allocation.reconciliation_variance, 0.0, places=2)

    def test_a_row_with_no_source_figure_is_never_offered_for_reconciliation(self):
        # None = no figure on file (an explicit 0.0 would be a supplied fact).
        allocation = self._allocation(None)
        self.assertFalse(allocation.has_source_data)
        self.assertEqual(allocation.reconciliation_state, 'no_source')

    def test_sign_off_is_refused_before_accounting_entries_exist(self):
        allocation = self._allocation(200000.0)
        allocation.reconciliation_note = 'Awaiting entries'
        with self.assertRaises(UserError):
            allocation.action_sign_off()

    def test_sign_off_is_refused_when_the_source_had_no_figure(self):
        allocation = self._allocation(None)
        allocation.reconciliation_note = 'Nothing to reconcile'
        with self.assertRaises(UserError):
            allocation.action_sign_off()

    # -- Once accounting entries exist ---
    def test_matching_entries_reconcile_as_matched(self):
        invoice = self.create_invoice(self.contract, 1000000.0)
        self.pay_into_escrow(invoice, 200000.0, project=self.project)

        allocation = self._allocation(200000.0)
        self.assertAlmostEqual(allocation.ledger_invoiced_amount, 1000000.0, places=2)
        self.assertAlmostEqual(allocation.ledger_received_in_escrow, 200000.0, places=2)
        self.assertAlmostEqual(allocation.reconciliation_variance, 0.0, places=2)
        self.assertEqual(allocation.reconciliation_state, 'matched')

    def test_a_differing_receipt_is_reported_as_a_variance(self):
        invoice = self.create_invoice(self.contract, 1000000.0)
        self.pay_into_escrow(invoice, 150000.0, project=self.project)

        allocation = self._allocation(200000.0)
        self.assertAlmostEqual(allocation.reconciliation_variance, 50000.0, places=2)
        self.assertEqual(allocation.reconciliation_state, 'variance')

    def test_receipts_to_the_wrong_bank_are_not_counted_as_escrow(self):
        """The whole point: money outside escrow does not satisfy the escrow side."""
        invoice = self.create_invoice(self.contract, 1000000.0)
        self.param_set_policy_off()
        payment = self.receive_into(invoice, 200000.0, self.foreign_bank_journal)
        payment.action_post()

        allocation = self._allocation(200000.0)
        self.assertAlmostEqual(allocation.ledger_received_amount, 200000.0, places=2)
        self.assertAlmostEqual(
            allocation.ledger_received_in_escrow, 0.0, places=2,
            msg='A receipt into a non-escrow bank must not count toward escrow.')
        self.assertEqual(allocation.reconciliation_state, 'variance')

    def test_sign_off_records_who_and_when(self):
        invoice = self.create_invoice(self.contract, 1000000.0)
        self.pay_into_escrow(invoice, 200000.0, project=self.project)

        allocation = self._allocation(200000.0)
        self.assertFalse(allocation.reconciled)
        with self.assertRaises(UserError):
            allocation.action_sign_off()  # note missing

        allocation.reconciliation_note = 'Matches escrow agent report 2026-05.'
        allocation.action_sign_off()
        self.assertTrue(allocation.reconciled)
        self.assertEqual(allocation.reconciled_by, self.env.user)
        self.assertTrue(allocation.reconciled_on)

        allocation.action_clear_sign_off()
        self.assertFalse(allocation.reconciled)

    def test_outstanding_figure_is_invoiced_less_received(self):
        invoice = self.create_invoice(self.contract, 1000000.0)
        self.pay_into_escrow(invoice, 250000.0, project=self.project)

        allocation = self._allocation(200000.0)
        self.assertAlmostEqual(allocation.ledger_open_amount, 750000.0, places=2)

    # -- The batch compute must not create anything ---
    def test_reading_the_register_creates_no_accounting_entries(self):
        invoice = self.create_invoice(self.contract, 1000000.0)
        self.pay_into_escrow(invoice, 200000.0, project=self.project)
        before = self.env['account.move'].search_count([])

        allocations = self._allocation(200000.0)
        allocations.invalidate_recordset()
        allocations._compute_ledger_totals()
        # More register activity on a second unit: still no ledger writes.
        other_unit = self.create_unit(self.project, '102')
        other_contract = self.create_contract(
            other_unit, self.buyer, sale_price=1000000.0)
        self._allocation(150000.0, unit=other_unit, contract=other_contract)

        self.assertEqual(
            self.env['account.move'].search_count([]), before,
            'Reading and reconciling the register must never write to the ledger.')

    def param_set_policy_off(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'sgc_escrow.payment_policy', 'off')