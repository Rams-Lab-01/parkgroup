# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Entitlement arithmetic and the over-release guard.

The formula under test::

    entitled   = received x (progress / 100) x (1 - retention / 100)
    releasable = max(0, entitled - released)
"""

from odoo.exceptions import AccessError, UserError, ValidationError

from .common import EscrowCommon


class TestEscrowEntitlement(EscrowCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.param = cls.env['ir.config_parameter'].sudo()
        cls._original_posting = cls.param.get_param('sgc_escrow.posting_enabled')

    def setUp(self):
        super().setUp()
        # These tests exercise real posting; the shipped default is deferred
        # (see TestEscrowPostingDeferred), so opt in for this class only.
        self.param.set_param('sgc_escrow.posting_enabled', 'True')
        self.project = self.setup_project(escrow=True, progress=0.0, retention=5.0)
        self.unit = self.create_unit(self.project)
        self.buyer = self.create_partner()
        self.contract = self.create_contract(self.unit, self.buyer)
        self.invoice = self.create_invoice(self.contract, amount=1000000.0)

    def tearDown(self):
        # Restore so test order cannot change the suite's behaviour.
        self.param.set_param('sgc_escrow.posting_enabled',
                             self._original_posting or False)
        super().tearDown()

    # -- Roll-ups ---
    def test_received_and_balance_track_the_ledger(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.escrow_received_amount, 400000.0, places=2)
        self.assertAlmostEqual(self.project.escrow_released_amount, 0.0, places=2)
        self.assertAlmostEqual(self.project.escrow_balance_amount, 400000.0, places=2)

    def test_entitlement_is_zero_before_any_progress_is_certified(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 0.0)
        self.assertAlmostEqual(self.project.escrow_entitled_amount, 0.0, places=2)
        self.assertAlmostEqual(self.project.escrow_releasable_amount, 0.0, places=2)

    def test_entitlement_applies_progress_then_retention(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        # 400,000 x 50% x (1 - 5%) = 190,000
        self.set_progress(self.project, 50.0)
        self.assertAlmostEqual(self.project.escrow_entitled_amount, 190000.0, places=2)
        self.assertAlmostEqual(self.project.escrow_releasable_amount, 190000.0, places=2)

    def test_zero_retention_releases_the_whole_entitlement(self):
        """0% retention at 100% progress makes the entire receipt releasable."""
        project = self.setup_project(progress=100.0, retention=0.0, code='SGCT0')
        unit = self.create_unit(project)
        buyer = self.create_partner('SGCEscrow Zero Retention')
        invoice = self.create_invoice(self.create_contract(unit, buyer), 1000000.0)

        self.pay_into_escrow(invoice, 400000.0, project=project)
        self.assertAlmostEqual(project.escrow_entitled_amount, 400000.0, places=2)
        self.assertAlmostEqual(project.escrow_releasable_amount, 400000.0, places=2)

    def test_full_retention_blocks_everything(self):
        """100% retention means nothing is releasable at any progress level."""
        project = self.setup_project(progress=100.0, retention=100.0, code='SGCTF')
        unit = self.create_unit(project)
        buyer = self.create_partner('SGCEscrow Full Retention')
        invoice = self.create_invoice(self.create_contract(unit, buyer), 1000000.0)

        self.pay_into_escrow(invoice, 400000.0, project=project)
        self.assertAlmostEqual(project.escrow_entitled_amount, 0.0, places=2)
        self.assertAlmostEqual(project.escrow_releasable_amount, 0.0, places=2)

    def test_releasable_shrinks_after_a_release(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)  # entitlement 190,000

        release = self.create_release(self.project, amount=150000.0)
        release.action_approve()
        release.action_post()
        self.project.invalidate_recordset()

        self.assertAlmostEqual(self.project.escrow_released_amount, 150000.0, places=2)
        self.assertAlmostEqual(self.project.escrow_balance_amount, 250000.0, places=2)
        # Entitlement is unchanged (still cumulative), but less is now available.
        self.assertAlmostEqual(self.project.escrow_entitled_amount, 190000.0, places=2)
        self.assertAlmostEqual(self.project.escrow_releasable_amount, 40000.0, places=2)

    def test_entitlement_never_goes_negative(self):
        """Releasing the whole entitlement leaves zero available, not negative."""
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)

        release = self.create_release(self.project, amount=190000.0)
        release.action_approve()
        release.action_post()
        self.project.invalidate_recordset()

        self.assertAlmostEqual(self.project.escrow_releasable_amount, 0.0, places=2)

    def test_escrow_disabled_zeroes_the_entitlement(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 80.0)
        self.assertGreater(self.project.escrow_entitled_amount, 0.0)

        self.project.escrow_enabled = False
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.escrow_entitled_amount, 0.0, places=2)
        self.assertAlmostEqual(self.project.escrow_releasable_amount, 0.0, places=2)

    # -- The guard ---
    def test_release_above_entitlement_is_refused(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 10.0)  # entitlement 38,000

        release = self.create_release(self.project, amount=100000.0)
        with self.assertRaises(UserError):
            release.action_approve()

    def test_over_release_needs_the_override_flag(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 10.0)  # entitlement 38,000

        release = self.create_release(self.project, amount=100000.0)
        release.is_override = True
        # Still refused: an override without a written reason is not a decision.
        with self.assertRaises(UserError):
            release.action_approve()

    def test_override_with_reason_is_accepted(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 10.0)  # entitlement 38,000

        release = self.create_release(self.project, amount=100000.0)
        release.is_override = True
        release.override_reason = 'RERA sanction RA/2026/114 - emergency works.'
        # Escalate to an Escrow Manager so the authorisation check passes.
        manager = self._escrow_manager()
        release.with_user(manager).action_approve()
        self.assertEqual(release.state, 'approved')

        release.with_user(manager).action_post()
        self.assertEqual(release.state, 'posted')
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.escrow_released_amount, 100000.0, places=2)

    def test_release_requires_positive_amount(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        release = self.create_release(self.project, amount=0.0)
        self.assertEqual(release.state, 'draft')
        # approve() re-checks and refuses
        with self.assertRaises(UserError):
            release.action_approve()

    # -- Posting mechanics ---
    def test_posting_moves_money_and_tags_the_entry(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)

        release = self.create_release(self.project, amount=100000.0)
        release.action_approve()
        release.action_post()

        self.assertEqual(release.state, 'posted')
        self.assertTrue(release.journal_entry_id)
        self.assertEqual(release.journal_entry_id.state, 'posted')
        self.assertEqual(release.journal_entry_id.escrow_release_id, release)
        self.assertTrue(release.journal_entry_id.is_escrow_release)

        # Two lines: credit escrow, debit operating.
        self.assertEqual(len(release.journal_entry_id.line_ids), 2)
        escrow_line = release.journal_entry_id.line_ids.filtered(
            lambda l: l.account_id == self.project.escrow_account_id)
        self.assertAlmostEqual(escrow_line.credit, 100000.0, places=2)
        self.assertAlmostEqual(escrow_line.debit, 0.0, places=2)

    def test_posting_requires_approval_first(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        release = self.create_release(self.project, amount=100000.0)
        with self.assertRaises(UserError):
            release.action_post()

    def test_snapshots_freeze_on_approval(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        release = self.create_release(self.project, amount=100000.0)
        self.assertAlmostEqual(release.certified_progress_snapshot, 50.0, places=2)
        self.assertAlmostEqual(release.releasable_snapshot, 190000.0, places=2)

        # Progress moves after drafting; the document must not follow it.
        self.set_progress(self.project, 90.0)
        self.assertAlmostEqual(release.certified_progress_snapshot, 50.0, places=2)
        self.assertAlmostEqual(release.releasable_snapshot, 190000.0, places=2)

    def test_reverse_returns_money_to_escrow(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)

        release = self.create_release(self.project, amount=100000.0)
        release.action_approve()
        release.action_post()
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.escrow_balance_amount, 300000.0, places=2)

        release.action_reverse()
        self.project.invalidate_recordset()
        self.assertEqual(release.state, 'cancelled')
        self.assertAlmostEqual(self.project.escrow_balance_amount, 400000.0, places=2)

    # -- References ---
    def test_references_are_unique_at_insert_time(self):
        """The sequence must land in the INSERT, not in a deferred write.

        Renaming 'New' after super().create() left the UPDATE in the ORM
        cache, so the second row of a batch create -- or the next create of
        the same transaction, where nothing had flushed escrow_release yet --
        collided with the unique index on name.
        """
        batch = self.env['escrow.release'].create([
            {'project_id': self.project.id, 'date': '2026-02-01'},
            {'project_id': self.project.id, 'date': '2026-02-01'},
        ])
        first = self.env['escrow.release'].create(
            {'project_id': self.project.id, 'date': '2026-02-01'})
        second = self.env['escrow.release'].create(
            {'project_id': self.project.id, 'date': '2026-02-01'})

        names = (batch | first | second).mapped('name')
        self.assertEqual(len(names), 4)
        self.assertEqual(len(set(names)), 4, names)
        for name in names:
            self.assertTrue(name.startswith('ESC/REL/'), name)

    def test_cannot_cancel_a_posted_release(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        release = self.create_release(self.project, amount=100000.0)
        release.action_approve()
        release.action_post()
        with self.assertRaises(UserError):
            release.action_cancel()

    def test_release_requires_escrow_enabled(self):
        project = self.setup_project(escrow=False, code='SGCTX')
        with self.assertRaises(Exception):
            self.env['escrow.release'].create({
                'project_id': project.id,
                'date': '2026-02-01',
            })

    # -- The direct-write guard ---
    def test_state_cannot_be_written_directly(self):
        """Write access must not be enough to jump a release to posted.

        The Approver role needs write access to let action_approve()/
        action_post() transition the record. Without this guard that same
        permission would let a caller bypass the entitlement check entirely
        with one RPC call.
        """
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        release = self.create_release(self.project, amount=100000.0)

        with self.assertRaises(AccessError):
            release.write({'state': 'posted'})

    def test_frozen_snapshots_cannot_be_rewritten(self):
        """The figures an approval was measured against are immutable."""
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        release = self.create_release(self.project, amount=100000.0)

        with self.assertRaises(AccessError):
            release.write({'releasable_snapshot': 9999999.0})
        with self.assertRaises(AccessError):
            release.write({'certified_progress_snapshot': 100.0})

    def test_journal_entry_link_cannot_be_forged(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        release = self.create_release(self.project, amount=100000.0)
        with self.assertRaises(AccessError):
            release.write({'journal_entry_id': self.invoice.id})

    def test_editable_fields_are_still_writable(self):
        """The guard must not block ordinary draft editing."""
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        release = self.create_release(self.project, amount=100000.0)

        release.write({'notes': 'Funding August invoices', 'amount': 120000.0})
        self.assertEqual(release.notes, 'Funding August invoices')
        self.assertAlmostEqual(release.amount, 120000.0, places=2)

    def test_a_draft_may_hold_zero_when_nothing_is_releasable(self):
        """A release is a working document; zero is a legitimate draft value.

        Positivity is enforced at approval, not at draft, so a planner can open
        a release before any money or progress exists.
        """
        project = self.setup_project(progress=0.0, code='SGCT0R')
        release = self.env['escrow.release'].create({
            'project_id': project.id,
            'date': '2026-02-01',
        })
        self.assertEqual(release.state, 'draft')
        self.assertAlmostEqual(release.amount, 0.0, places=2)
        self.assertAlmostEqual(release.releasable_snapshot, 0.0, places=2)

    def test_negative_amount_is_always_refused(self):
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 50.0)
        release = self.create_release(self.project, amount=100000.0)
        with self.assertRaises(ValidationError):
            release.write({'amount': -1.0})