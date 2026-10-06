# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Shared fixture for the escrow test suite.

Builds the minimum real structure the bridge depends on: a company with a chart,
an escrow bank journal plus an operating bank journal, and a project wired to
the escrow journal.
"""

from odoo.tests import common, tagged


@tagged('post_install', '-at_install')
class EscrowCommon(common.TransactionCase):
    """Base class with accounting + property fixtures."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        cls.escrow_journal = cls._create_bank_journal('SGCEsc Test Escrow', 'SGCE')
        cls.operating_journal = cls._create_bank_journal('SGCEsc Test Op', 'SGCO')
        cls.foreign_bank_journal = cls._create_bank_journal('SGCEsc Test Wrong', 'SGCW')

        cls.product = cls.env['product.product'].create({
            'name': 'SGCEscrow Installment',
            'type': 'service',
            'list_price': 1000.0,
            'company_id': cls.company.id,
        })

    @classmethod
    def _create_bank_journal(cls, name, code):
        journal = cls.env['account.journal'].create({
            'name': name,
            'code': code,
            'type': 'bank',
            'company_id': cls.company.id,
        })
        # Odoo creates the liquidity account for a bank journal automatically;
        # assert here so a failure names the cause instead of surfacing later
        # as an unexplained zero balance.
        assert journal.default_account_id, (
            'Bank journal %s did not get a default account' % code)
        return journal

    @classmethod
    def _next_code(cls, stem):
        """A free 5-char journal code, so each fixture journal is unique."""
        cls._code_seq = getattr(cls, '_code_seq', 0) + 1
        return '%s%d' % (stem[:4], cls._code_seq % 100)

    # -- Structure ---
    @classmethod
    def setup_project(cls, escrow=True, progress=0.0, retention=5.0, code='SGCT',
                      own_journal=True):
        """A project wired to its own escrow bank journal.

        Each project gets a dedicated journal because that is what the module
        enforces in production: one escrow account per project. Reusing a shared
        journal would (correctly) trip the uniqueness constraint.
        """
        if own_journal:
            escrow_journal = cls._create_bank_journal(
                'SGCEsc Escrow %s' % code, cls._next_code('SE'))
        else:
            escrow_journal = cls.escrow_journal
        return cls.env['property.project'].create({
            'name': 'SGCEscrow Test Project',
            'code': code,
            'company_id': cls.company.id,
            'escrow_enabled': escrow,
            'escrow_bank_journal_id': escrow_journal.id,
            'escrow_release_journal_id': cls.operating_journal.id,
            'escrow_retention_pct': retention,
            'escrow_certified_progress': progress,
            'escrow_certified_date': '2026-01-15',
        })

    @classmethod
    def create_unit(cls, project, unit_number='101', sale_price=1000000.0):
        return cls.env['property.details'].create({
            'name': 'SGCEscrow Unit %s' % unit_number,
            'unit_number': unit_number,
            'project_id': project.id,
            'sale_price': sale_price,
            'company_id': cls.company.id,
        })

    @classmethod
    def create_partner(cls, name='SGCEscrow Buyer'):
        return cls.env['res.partner'].create({'name': name})

    @classmethod
    def create_contract(cls, unit, buyer, sale_price=1000000.0):
        return cls.env['sale.contract'].create({
            'name': 'SGCEscrow Contract %s' % unit.unit_number,
            'property_id': unit.id,
            'buyer_id': buyer.id,
            'sale_price': sale_price,
            'company_id': cls.company.id,
        })

    @classmethod
    def create_invoice(cls, contract, amount=1000000.0):
        """A posted customer invoice carrying the contract's escrow project."""
        move = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': contract.buyer_id.id,
            'invoice_date': '2026-01-01',
            'company_id': cls.company.id,
            'currency_id': cls.company.currency_id.id,
            'sold_id': contract.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': cls.product.id,
                'name': 'Unit sale',
                'quantity': 1,
                'price_unit': amount,
            })],
        })
        move.action_post()
        return move

    # -- Money ---
    @classmethod
    def _register_payment(cls, invoice, amount, journal, post=True):
        """Receive ``amount`` of a posted invoice into ``journal``.

        Goes through ``account.payment.register`` rather than writing
        ``account.payment.line_ids`` by hand: the wizard is the supported API for
        reconciling a payment to specific invoice lines, and it is also the code
        path the module's routing override touches -- so the fixture exercises
        the real flow rather than a shortcut past it.
        """
        receivable = invoice.line_ids.filtered(
            lambda line: line.account_id.account_type == 'asset_receivable')[:1]
        wizard = cls.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'payment_date': '2026-01-05',
            'amount': amount,
            'journal_id': journal.id,
            'line_ids': [(6, 0, receivable.ids)],
        })
        payments = wizard._create_payments()
        if not post:
            return payments
        return payments

    @classmethod
    def pay_into_escrow(cls, invoice, amount, project=None):
        """Compliant receipt: money lands in the project's escrow account."""
        journal = (project or invoice.escrow_project_id).escrow_bank_journal_id
        payments = cls._register_payment(invoice, amount, journal)
        for payment in payments:
            if payment.state == 'draft':
                payment.action_post()
        return payments

    @classmethod
    def receive_into(cls, invoice, amount, journal):
        """Register a receipt into an arbitrary journal, left in draft.

        Deliberately returns the draft payment so the caller can exercise the
        policy guard at ``action_post()`` time.
        """
        payments = cls._register_payment(invoice, amount, journal, post=False)
        return payments[:1]

    # -- Releases ---
    @classmethod
    def set_progress(cls, project, progress):
        """Certify progress and re-baseline any draft release on the project."""
        project.escrow_certified_progress = progress
        project.escrow_release_ids.filtered(
            lambda r: r.state == 'draft').action_refresh_snapshots()

    @classmethod
    def create_release(cls, project, amount=None, date='2026-02-01'):
        """Draft a release; the default amount is the full entitlement."""
        release = cls.env['escrow.release'].create({
            'project_id': project.id,
            'date': date,
        })
        if amount is not None:
            release.amount = amount
        return release