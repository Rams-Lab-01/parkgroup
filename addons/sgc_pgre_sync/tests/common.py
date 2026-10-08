# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Shared fixture for the PGRE sync test suite: a fake remote client plus the
minimum local accounting structure (journal, partner, receivable account) and
canned source payloads shaped exactly like pgre search_read output.
"""

from odoo import fields
from odoo.tests import common, tagged

# Canned PGRE-side ids used across the tests
SRC_JOURNAL_ID = 701
SRC_BANK_JOURNAL_ID = 702
SRC_PARTNER_ID = 9001
SRC_NEW_PARTNER_ID = 9002
SRC_RECEIVABLE_ID = 3001
SRC_MOVE_ID = 5001
SRC_MOVE_LINE_ID = 61001
SRC_MOVE_LINE_2_ID = 61002
SRC_PAYMENT_ID = 7001


def source_move(state='draft', line_ids=(SRC_MOVE_LINE_ID,), write_date='2026-10-07 08:00:00'):
    lines = list(line_ids)
    return {
        'id': SRC_MOVE_ID,
        'name': 'INV/2026/0001',
        'move_type': 'out_invoice',
        'state': state,
        'date': '2026-10-07',
        'invoice_date': '2026-10-07',
        'invoice_date_due': '2026-10-21',
        'ref': 'INV-5001',
        'partner_id': [SRC_PARTNER_ID, 'Test Buyer'],
        'journal_id': [SRC_JOURNAL_ID, 'Customer Invoices'],
        'currency_id': [1, 'AED'],
        'company_id': [1, 'PARK HOMES INTERNATIONAL REAL ESTATE LLC'],
        'invoice_line_ids': lines,
        'line_ids': [],
        'write_date': write_date,
    }


def source_move_line(line_id=SRC_MOVE_LINE_ID, name='Unit sale', quantity=1.0,
                     price_unit=1000.0):
    return {
        'id': line_id,
        'name': name,
        'quantity': quantity,
        'price_unit': price_unit,
        'account_id': [SRC_RECEIVABLE_ID, 'Accounts Receivable'],
        'tax_ids': [],
        'product_id': False,
        'display_type': 'product',
        'date': '2026-10-07',
        'price_subtotal': quantity * price_unit,
        'price_total': quantity * price_unit,
        'currency_id': [1, 'AED'],
        'write_date': '2026-10-07 08:00:00',
    }


def source_payment(state='draft', write_date='2026-10-07 09:00:00'):
    return {
        'id': SRC_PAYMENT_ID,
        'name': 'P-001',
        'payment_type': 'inbound',
        'partner_type': 'customer',
        'partner_id': [SRC_PARTNER_ID, 'Test Buyer'],
        'amount': 500.0,
        'currency_id': [1, 'AED'],
        'date': '2026-10-07',
        'journal_id': [SRC_BANK_JOURNAL_ID, 'Bank'],
        'memo': 'Rcpt 5001',
        'ref': '',
        'company_id': [1, 'PARK HOMES INTERNATIONAL REAL ESTATE LLC'],
        'state': state,
        'write_date': write_date,
    }


class FakeClient:
    """Offline stand-in for PgreRemote with canned search_read/read results."""

    def __init__(self, moves=None, move_lines=None, payments=None):
        self.moves = moves or []
        self.move_lines = move_lines or []
        self.payments = payments or []
        self.authenticated = False

    def authenticate(self):
        self.authenticated = True
        return 2

    def call(self, model, method, args, kwargs=None):
        raise AssertionError('FakeClient.call should not be used by the applier')

    def search_read(self, model, domain, fields, order=None, batch=500):
        if model == 'account.move':
            return list(self.moves)
        if model == 'account.payment':
            return list(self.payments)
        return []

    def read(self, model, ids, fields):
        if model != 'account.move.line':
            return []
        wanted = set(ids)
        return [dict(row) for row in self.move_lines if row['id'] in wanted]


@tagged('post_install', '-at_install')
class PgreSyncCommon(common.TransactionCase):
    """Base class: local journal + partner + bindings for the canned ids."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.journal = cls.env['account.journal'].create({
            'name': 'PGRESync Customer Invoices',
            'code': 'SYNCT',
            'type': 'sale',
            'company_id': cls.company.id,
        })
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'PGRESync Bank',
            'code': 'SYNBR',
            'type': 'bank',
            'company_id': cls.company.id,
        })
        cls.buyer = cls.env['res.partner'].create({'name': 'Test Buyer'})
        cls.receivable = cls.env['account.account'].search(
            [('account_type', '=', 'asset_receivable'),
             ('company_ids', 'in', cls.company.id)], limit=1)
        if not cls.receivable:
            cls.receivable = cls.env['account.account'].search(
                [('account_type', '=', 'asset_receivable')], limit=1)
        assert cls.receivable, 'No receivable account in the test chart'

        Binding = cls.env['pgre.sync.binding']
        cls.binding = lambda: Binding  # noqa: E731  (handy accessor in tests)
        Binding.bind('account.journal', SRC_JOURNAL_ID, cls.journal.id, False)
        Binding.bind('account.journal', SRC_BANK_JOURNAL_ID, cls.bank_journal.id, False)
        Binding.bind('res.partner', SRC_PARTNER_ID, cls.buyer.id, False)
        Binding.bind('account.account', SRC_RECEIVABLE_ID, cls.receivable.id, False)
        # currency: bind AED id 1 to the company currency
        Binding.bind('res.currency', 1, cls.company.currency_id.id, False)

        cls._params = cls.env['ir.config_parameter'].sudo()
        cls._set_param('pgre_sync.enabled', 'True')
        cls._set_param('pgre_sync.dry_run', 'False')

    @classmethod
    def _set_param(cls, key, value):
        existing = cls._params.search([('key', '=', key)], limit=1)
        if existing:
            existing.value = value
        else:
            cls._params.create({'key': key, 'value': value})

    @classmethod
    def tearDownClass(cls):
        for key in ('pgre_sync.enabled', 'pgre_sync.dry_run'):
            cls._params.search([('key', '=', key)]).unlink()
        super().tearDownClass()

    def _applier(self, fake, dry_run=False):
        from odoo.addons.sgc_pgre_sync.services.applier import PgreApplier
        return PgreApplier(self.env, fake, dry_run=dry_run)
