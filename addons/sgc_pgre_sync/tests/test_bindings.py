# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Binding table behaviour: uniqueness, idempotent bind(), lookups."""

from odoo.exceptions import ValidationError

from .common import PgreSyncCommon, SRC_JOURNAL_ID


class TestBinding(PgreSyncCommon):
    def test_bind_is_idempotent(self):
        Binding = self.env['pgre.sync.binding']
        first = Binding.bind('res.partner', SRC_JOURNAL_ID, 42, '2026-10-07 08:00:00')
        second = Binding.bind('res.partner', SRC_JOURNAL_ID, 42, '2026-10-07 08:00:00')
        self.assertEqual(first.id, second.id)
        self.assertEqual(len(Binding.search([('model', '=', 'res.partner'),
                                             ('pgre_id', '=', SRC_JOURNAL_ID)])), 1)

    def test_unique_model_pgre_id(self):
        Binding = self.env['pgre.sync.binding']
        Binding.create({'model': 'account.move', 'pgre_id': 4242, 'vps_id': 1})
        with self.assertRaises(ValidationError):
            Binding.create({'model': 'account.move', 'pgre_id': 4242, 'vps_id': 2})

    def test_get_binding_and_for_vps(self):
        Binding = self.env['pgre.sync.binding']
        self.assertTrue(Binding.get_binding('account.journal', SRC_JOURNAL_ID))
        self.assertFalse(Binding.get_binding('account.journal', 999999))
        found = Binding.for_vps('account.journal', self.journal.id)
        self.assertTrue(found)
        self.assertEqual(found.pgre_id, SRC_JOURNAL_ID)

    def test_same_pgre_id_different_models_allowed(self):
        Binding = self.env['pgre.sync.binding']
        Binding.create({'model': 'account.move', 'pgre_id': 777, 'vps_id': 1})
        Binding.create({'model': 'account.payment', 'pgre_id': 777, 'vps_id': 2})
        self.assertEqual(len(Binding.search([('pgre_id', '=', 777)])), 2)
