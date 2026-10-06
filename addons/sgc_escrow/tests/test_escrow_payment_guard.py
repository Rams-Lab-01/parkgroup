# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Payment routing and the warn/block/off escrow policy.

The guard is the mechanism that keeps "collected per unit" and "money in escrow"
equal. It must never move money itself, and the default (warn) must never be able
to stop the finance team.
"""

from odoo.exceptions import UserError

from .common import EscrowCommon


class TestEscrowPaymentGuard(EscrowCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.param = cls.env['ir.config_parameter'].sudo()
        cls._original_policy = cls.param.get_param('sgc_escrow.payment_policy')

    def setUp(self):
        super().setUp()
        self.project = self.setup_project(code='SGCG')
        self.unit = self.create_unit(self.project, '101')
        self.buyer = self.create_partner('SGCEscrow Guard Buyer')
        self.contract = self.create_contract(self.unit, self.buyer)
        self.invoice = self.create_invoice(self.contract, 1000000.0)
        self.param.set_param('sgc_escrow.payment_policy', 'off')

    def tearDown(self):
        # Restore so test order cannot change the suite's behaviour.
        if self._original_policy is None:
            self.param.set_param('sgc_escrow.payment_policy', False)
        else:
            self.param.set_param('sgc_escrow.payment_policy', self._original_policy)
        super().tearDown()

    # -- Routing ---
    def test_wizard_defaults_to_the_escrow_journal(self):
        """Pressing Register Payment on an escrow invoice opens on escrow."""
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=self.invoice.ids,
        ).create({})
        self.assertEqual(wizard.escrow_routing_project_id, self.project)
        self.assertEqual(wizard.journal_id, self.project.escrow_bank_journal_id)

    def test_escrow_journal_stays_selectable(self):
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=self.invoice.ids,
        ).create({})
        self.assertIn(
            self.project.escrow_bank_journal_id, wizard.available_journal_ids)

    def test_routing_depends_keep_the_base_triggers(self):
        """An override replaces @api.depends; dropping the base ones breaks routing.

        ``_compute_journal_id`` in account depends only on
        ``available_journal_ids``, and ``_compute_available_journal_ids`` on
        ``payment_type`` / ``company_id`` / ``can_edit_wizard``. Our overrides
        narrow neither, because narrowing would leave the journal default
        silently stale the moment the available journals changed.
        """
        fields = self.env['account.payment.register']._fields

        journal_depends = set(fields['journal_id'].depends)
        available_depends = set(fields['available_journal_ids'].depends)

        self.assertIn(
            'available_journal_ids', journal_depends,
            'base trigger for _compute_journal_id must be preserved')
        self.assertTrue(
            {'payment_type', 'company_id', 'can_edit_wizard'}.issubset(available_depends),
            'base triggers for _compute_available_journal_ids must be preserved')

        # Our own trigger, the one that makes routing escrow-aware.
        self.assertIn(
            'line_ids.move_id.escrow_project_id', journal_depends)
        self.assertIn(
            'line_ids.move_id.escrow_project_id', available_depends)

    def test_no_routing_when_escrow_is_off(self):
        self.project.escrow_enabled = False
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=self.invoice.ids,
        ).create({})
        self.assertFalse(wizard.escrow_routing_project_id)

    def test_no_routing_for_an_ordinary_invoice(self):
        """A rent invoice with no project must behave exactly as before."""
        rent_invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.buyer.id,
            'invoice_date': '2026-01-01',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'name': 'Unrelated service',
                'quantity': 1,
                'price_unit': 1000.0,
            })],
        })
        wizard = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=rent_invoice.ids,
        ).create({})
        self.assertFalse(wizard.escrow_routing_project_id)

    # -- Guard: block ---
    def test_block_policy_refuses_a_receipt_outside_escrow(self):
        self.param.set_param('sgc_escrow.payment_policy', 'block')
        payment = self.receive_into(
            self.invoice, 100000.0, self.foreign_bank_journal)
        with self.assertRaises(UserError):
            payment.action_post()

    def test_block_policy_allows_the_correct_escrow_journal(self):
        self.param.set_param('sgc_escrow.payment_policy', 'block')
        payment = self.pay_into_escrow(self.invoice, 100000.0, project=self.project)
        self.assertEqual(payment.state, 'posted')

    def test_block_policy_ignores_projects_without_escrow(self):
        self.project.escrow_enabled = False
        self.param.set_param('sgc_escrow.payment_policy', 'block')
        payment = self.receive_into(
            self.invoice, 100000.0, self.foreign_bank_journal)
        payment.action_post()
        self.assertEqual(payment.state, 'posted')

    def test_block_policy_ignores_outbound_payments(self):
        """Refunds out of escrow are not a violation."""
        self.param.set_param('sgc_escrow.payment_policy', 'block')
        payment = self.env['account.payment'].create({
            'payment_type': 'outbound',
            'partner_type': 'customer',
            'partner_id': self.buyer.id,
            'amount': 1000.0,
            'payment_date': '2026-01-05',
            'journal_id': self.foreign_bank_journal.id,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
        })
        self.assertFalse(payment._escrow_expected_project())
        self.assertEqual(
            payment._escrow_policy_violations(),
            [],
            'An outbound payment with no invoice behind it must not be policed.')

    # -- Guard: warn ---
    def test_warn_policy_posts_a_warning_and_still_posts(self):
        self.param.set_param('sgc_escrow.payment_policy', 'warn')
        message_count_before = len(self.invoice.message_ids)
        payment = self.receive_into(
            self.invoice, 100000.0, self.foreign_bank_journal)
        payment.action_post()

        self.assertEqual(payment.state, 'posted')
        self.assertGreater(
            len(self.invoice.message_ids), message_count_before,
            'The warning must land on the invoice for the audit trail.')

    def test_off_policy_says_nothing(self):
        self.param.set_param('sgc_escrow.payment_policy', 'off')
        payment = self.receive_into(
            self.invoice, 100000.0, self.foreign_bank_journal)
        self.assertEqual(payment._escrow_policy_violations(), [
            (payment, self.project),
        ], 'Detection still works; only enforcement is disabled.')
        payment.action_post()
        self.assertEqual(payment.state, 'posted')