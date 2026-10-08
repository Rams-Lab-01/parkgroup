# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Applier behaviour: dry-run safety, creation, idempotency, line diffing,
state transitions and the conflict guard."""

from .common import (
    FakeClient,
    PgreSyncCommon,
    SRC_MOVE_ID,
    SRC_MOVE_LINE_ID,
    SRC_NEW_PARTNER_ID,
    SRC_PAYMENT_ID,
    source_move,
    source_move_line,
    source_payment,
)

MOVE = 'account.move'
PAYMENT = 'account.payment'


class TestApplierMove(PgreSyncCommon):
    def _mirror_move(self):
        return self.env['account.move'].search([('ref', '=', '[PHI] INV-5001')])


class TestApplierMove(PgreSyncCommon):
    def test_dry_run_creates_nothing(self):
        fake = FakeClient(moves=[source_move()], move_lines=[source_move_line()])
        applier = self._applier(fake, dry_run=True)
        counts = applier.apply_records(MOVE, [source_move()])
        self.assertEqual(counts['processed'], 1)
        self.assertFalse(self.env['account.move'].search([('ref', '=', '[PHI] INV-5001')]))
        self.assertFalse(self.env['pgre.sync.binding'].get_binding(MOVE, SRC_MOVE_ID))
        log = self.env['pgre.sync.log'].search([('model', '=', MOVE)])
        self.assertTrue(log)
        self.assertTrue(all(entry.dry_run for entry in log))

    def test_create_draft_move_with_bindings(self):
        fake = FakeClient(move_lines=[source_move_line()])
        applier = self._applier(fake)
        counts = applier.apply_records(MOVE, [source_move()])
        self.assertEqual(counts['created'], 1)
        move = self._mirror_move()
        self.assertEqual(len(move), 1)
        self.assertEqual(move.state, 'draft')
        self.assertEqual(move.ref, '[PHI] INV-5001')
        self.assertEqual(len(move.invoice_line_ids), 1)
        binding = self.env['pgre.sync.binding'].get_binding(MOVE, SRC_MOVE_ID)
        self.assertEqual(binding.vps_id, move.id)
        self.assertEqual(binding.state, 'synced')
        # the source line is bound to the mirror line
        line_binding = self.env['pgre.sync.binding'].get_binding(
            'account.move.line', SRC_MOVE_LINE_ID)
        self.assertEqual(line_binding.vps_id, move.invoice_line_ids[0].id)

    def test_create_posted_move_calls_action_post(self):
        fake = FakeClient(move_lines=[source_move_line()])
        applier = self._applier(fake)
        applier.apply_records(MOVE, [source_move(state='posted')])
        move = self._mirror_move()
        self.assertEqual(move.state, 'posted')

    def test_second_run_skips(self):
        fake = FakeClient(move_lines=[source_move_line()])
        applier = self._applier(fake)
        applier.apply_records(MOVE, [source_move()])
        before = self._mirror_move().search_count([])
        counts = applier.apply_records(MOVE, [source_move()])
        self.assertEqual(counts['skipped'], 1)
        self.assertEqual(self._mirror_move().search_count([]), before)

    def test_missing_partner_is_auto_created_minimal(self):
        fake = FakeClient(move_lines=[source_move_line()])
        move_payload = source_move()
        move_payload['partner_id'] = [SRC_NEW_PARTNER_ID, 'Fresh Buyer From PGRE']
        applier = self._applier(fake)
        applier.apply_records(MOVE, [move_payload])
        partner = self.env['res.partner'].search([('name', '=', 'Fresh Buyer From PGRE')])
        self.assertEqual(len(partner), 1)
        binding = self.env['pgre.sync.binding'].get_binding('res.partner', SRC_NEW_PARTNER_ID)
        self.assertEqual(binding.vps_id, partner.id)
        self.assertEqual(binding.state, 'needs_review')

    def test_unresolvable_journal_parks_record(self):
        fake = FakeClient(move_lines=[source_move_line()])
        move_payload = source_move()
        move_payload['journal_id'] = [777777, 'No Such Journal']
        applier = self._applier(fake)
        counts = applier.apply_records(MOVE, [move_payload])
        self.assertEqual(counts['errors'], 1)
        self.assertFalse(self.env['account.move'].search([('ref', '=', '[PHI] INV-5001')]))

    def test_removed_source_line_deletes_mirror_line(self):
        fake = FakeClient(move_lines=[source_move_line()])
        applier = self._applier(fake)
        applier.apply_records(MOVE, [source_move()])
        move = self._mirror_move()
        self.assertEqual(len(move.invoice_line_ids), 1)
        # source line vanishes: empty invoice_line_ids
        applier.apply_records(MOVE, [source_move(line_ids=(), write_date='2026-10-08 08:00:00')])
        self.assertFalse(move.invoice_line_ids)
        self.assertFalse(self.env['pgre.sync.binding'].get_binding(
            'account.move.line', SRC_MOVE_LINE_ID))

    def test_posted_move_lines_never_touched(self):
        fake = FakeClient(move_lines=[source_move_line()])
        applier = self._applier(fake)
        applier.apply_records(MOVE, [source_move(state='posted')])
        move = self._mirror_move()
        line_before = move.line_ids[0].id
        # source now has an extra line; mirror must refuse to touch posted lines
        applier.apply_records(MOVE, [source_move(
            state='posted', line_ids=(SRC_MOVE_LINE_ID, 61099),
            write_date='2026-10-08 08:00:00')])
        binding = self.env['pgre.sync.binding'].get_binding(MOVE, SRC_MOVE_ID)
        self.assertEqual(binding.state, 'needs_review')
        move.invalidate_recordset()
        self.assertEqual(move.line_ids[0].id, line_before)

    def test_local_edit_triggers_conflict_then_source_wins(self):
        fake = FakeClient(move_lines=[source_move_line()])
        applier = self._applier(fake)
        applier.apply_records(MOVE, [source_move()])
        move = self._mirror_move()
        binding = self.env['pgre.sync.binding'].get_binding(MOVE, SRC_MOVE_ID)
        binding.last_applied = '2026-10-07 00:00:00'  # make the guard deterministic
        move.write({'ref': 'locally edited'})  # simulate a VPS-side edit
        counts = applier.apply_records(
            MOVE, [source_move(state='draft', write_date='2026-10-08 08:00:00')])
        self.assertEqual(counts['updated'], 1)
        self.assertEqual(move.ref, '[PHI] INV-5001')
        self.assertEqual(binding.state, 'conflict')
        conflict_log = self.env['pgre.sync.log'].search([
            ('action', '=', 'conflict'), ('pgre_id', '=', SRC_MOVE_ID)])
        self.assertTrue(conflict_log)


class TestApplierPayment(PgreSyncCommon):
    def _mirror_payment(self):
        return self.env['account.payment'].search([('memo', '=', '[PHI] Rcpt 5001')])

    def test_create_and_post_payment(self):
        fake = FakeClient()
        applier = self._applier(fake)
        counts = applier.apply_records(PAYMENT, [source_payment()])
        self.assertEqual(counts['created'], 1)
        payment = self._mirror_payment()
        self.assertEqual(len(payment), 1)
        self.assertEqual(payment.state, 'draft')
        counts = applier.apply_records(PAYMENT, [source_payment(state='posted',
                                                               write_date='2026-10-07 10:00:00')])
        self.assertEqual(counts['updated'], 1)
        self.assertEqual(payment.state, 'posted')

    def test_cancelled_source_deletes_draft_mirror(self):
        fake = FakeClient()
        applier = self._applier(fake)
        applier.apply_records(PAYMENT, [source_payment()])
        payment = self._mirror_payment()
        counts = applier.apply_records(
            PAYMENT, [source_payment(state='cancel', write_date='2026-10-07 11:00:00')])
        self.assertEqual(counts['deleted'], 1)
        self.assertFalse(payment.exists())
        self.assertFalse(self.env['pgre.sync.binding'].get_binding(PAYMENT, SRC_PAYMENT_ID))
