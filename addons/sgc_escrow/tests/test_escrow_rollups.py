# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Attribution and ledger-consistency checks.

The claim this module makes is narrow and load-bearing: *the Odoo ledger is the
escrow ledger*. These tests verify that statement rather than trusting it.
"""

from odoo.exceptions import ValidationError

from .common import EscrowCommon


class TestEscrollRollups(EscrowCommon):

    def setUp(self):
        super().setUp()
        self.project = self.setup_project(code='SGCR')
        self.unit = self.create_unit(self.project, '101')
        self.buyer = self.create_partner('SGCEscrow Rollup Buyer')
        self.contract = self.create_contract(self.unit, self.buyer)
        self.invoice = self.create_invoice(self.contract, 1000000.0)

    # -- Attribution ---
    def test_invoice_inherits_the_project_from_its_unit(self):
        self.assertEqual(self.invoice.escrow_project_id, self.project)
        self.assertEqual(self.contract.escrow_project_id, self.project)

    def test_move_lines_inherit_project_attribution(self):
        lines = self.invoice.line_ids.filtered('escrow_project_id')
        self.assertTrue(lines)
        for line in lines:
            self.assertEqual(line.escrow_project_id, self.project)

    def test_ledger_totals_equal_a_raw_query_of_the_escrow_account(self):
        """The roll-up must be the ledger, not a parallel tally."""
        self.pay_into_escrow(self.invoice, 250000.0)

        raw = self.env['account.move.line'].search([
            ('account_id', '=', self.project.escrow_account_id.id),
            ('parent_state', '=', 'posted'),
        ]).mapped('balance')
        self.project.invalidate_recordset()

        self.assertAlmostEqual(
            self.project.escrow_received_amount, sum(raw), places=2)
        self.assertEqual(raw, [250000.0])

    def test_draft_entries_are_excluded_from_the_rollup(self):
        """Unposted money is not in escrow, however real the invoice looks."""
        draft_invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'partner_id': self.buyer.id,
            'invoice_date': '2026-03-01',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'sold_id': self.contract.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.product.id,
                'name': 'Draft unit sale',
                'quantity': 1,
                'price_unit': 500000.0,
            })],
        })
        self.assertEqual(draft_invoice.state, 'draft')
        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.escrow_received_amount, 0.0, places=2)

    def test_a_manual_transfer_out_is_not_counted_as_an_authorised_release(self):
        """Correctness beats convenience: only escrow.release counts as released.

        Money can leave an escrow account through a manual journal entry. That
        still reduces the balance, but it is not an authorised release, so it
        must not inflate the amount considered already spent against the
        entitlement -- otherwise the ceiling silently drifts.
        """
        self.pay_into_escrow(self.invoice, 400000.0)
        self.set_progress(self.project, 100.0)  # 95% retention -> 380,000

        # Manual entry: escrow -> operating, with no escrow.release tag.
        self.env['account.move'].create({
            'journal_id': self.project.escrow_bank_journal_id.id,
            'date': '2026-01-10',
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': self.project.escrow_account_id.id,
                    'name': 'Manual transfer out',
                    'credit': 50000.0,
                }),
                (0, 0, {
                    'account_id': self.operating_journal.default_account_id.id,
                    'name': 'Manual transfer in',
                    'debit': 50000.0,
                }),
            ],
        }).action_post()

        self.project.invalidate_recordset()
        self.assertAlmostEqual(self.project.escrow_balance_amount, 350000.0, places=2)
        # The unauthorised 50,000 must NOT reduce the releasable ceiling.
        self.assertAlmostEqual(self.project.escrow_released_amount, 0.0, places=2)
        self.assertAlmostEqual(self.project.escrow_releasable_amount, 380000.0, places=2)

    # -- Statement consistency ---
    def test_project_rollups_sum_the_allocation_register(self):
        Allocation = self.env['escrow.allocation']
        for index, allocated in enumerate([100000.0, 0.0, 50000.0], start=1):
            unit = self.create_unit(self.project, '2%02d' % index)
            Allocation.create({
                'project_id': self.project.id,
                'unit_id': unit.id,
                'company_id': self.company.id,
                'currency_id': self.company.currency_id.id,
                'sale_price_snapshot': 1000000.0,
                'escrow_pct': 10.0,
                'allocated_amount': allocated,
            })
        self.project.invalidate_recordset()

        allocations = Allocation.search([('project_id', '=', self.project.id)])
        self.assertAlmostEqual(
            self.project.escrow_allocation_allocated_amount,
            sum(allocations.mapped('allocated_amount')), places=2)
        self.assertAlmostEqual(
            self.project.escrow_allocation_required_amount,
            sum(allocations.mapped('required_amount')), places=2)
        self.assertAlmostEqual(
            self.project.escrow_allocation_variance_amount,
            sum(allocations.mapped('variance_amount')), places=2)

    def test_unit_and_contract_summaries_agree_with_the_register(self):
        Allocation = self.env['escrow.allocation']
        allocation = Allocation.create({
            'project_id': self.project.id,
            'unit_id': self.unit.id,
            'contract_id': self.contract.id,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'sale_price_snapshot': 1000000.0,
            'escrow_pct': 10.0,
            'allocated_amount': 90000.0,
        })
        self.unit.invalidate_recordset()
        self.contract.invalidate_recordset()

        self.assertAlmostEqual(self.unit.escrow_amount_allocated, 90000.0, places=2)
        self.assertAlmostEqual(self.contract.escrow_amount_allocated, 90000.0, places=2)
        self.assertAlmostEqual(
            self.unit.escrow_amount_variance,
            allocation.variance_amount, places=2)
        self.assertTrue(self.unit.escrow_has_source_data)

    # -- Project configuration guards ---
    def test_one_escrow_account_per_project(self):
        with self.assertRaises(ValidationError):
            self.setup_project(code='SGCR2', own_journal=False)

    def test_escrow_cannot_be_enabled_without_a_journal(self):
        with self.assertRaises(ValidationError):
            self.env['property.project'].create({
                'name': 'SGCEscrow No Journal',
                'code': 'SGCNJ',
                'company_id': self.company.id,
                'escrow_enabled': True,
            })

    def test_setup_action_creates_a_working_escrow_account(self):
        project = self.env['property.project'].create({
            'name': 'SGCEscrow Fresh',
            'code': 'SGCFR',
            'company_id': self.company.id,
        })
        project.action_setup_escrow_journal()

        self.assertTrue(project.escrow_enabled)
        self.assertEqual(project.escrow_bank_journal_id.type, 'bank')
        self.assertTrue(project.escrow_account_id)

    def test_setup_action_is_refused_when_a_journal_already_exists(self):
        with self.assertRaises(ValidationError):
            self.project.action_setup_escrow_journal()