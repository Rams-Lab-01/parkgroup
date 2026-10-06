# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""The allocation register: required vs allocated, and the importer.

The register's whole job is to hold the truth about a figure the source may not
have supplied. The critical behaviour is therefore: *absent stays absent*. A
missing allocation must never become a zero, because zero reconciles cleanly and
a wrong zero is worse than a visible gap.
"""

import base64
import json

from odoo.exceptions import ValidationError

from .common import EscrowCommon


class TestEscrowAllocation(EscrowCommon):

    def setUp(self):
        super().setUp()
        self.project = self.setup_project(code='SGCA')
        self.unit = self.create_unit(self.project, '101', sale_price=2209581.1)
        self.buyer = self.create_partner('MACHIEL DE VRIES')
        self.contract = self.create_contract(
            self.unit, self.buyer, sale_price=2209581.1)

    def _allocation(self, **vals):
        base = {
            'project_id': self.project.id,
            'unit_id': self.unit.id,
            'contract_id': self.contract.id,
            'company_id': self.company.id,
            'currency_id': self.company.currency_id.id,
            'source_reference': 'test',
        }
        base.update(vals)
        return self.env['escrow.allocation'].create(base)

    # -- Arithmetic ---
    def test_required_is_sale_price_times_percentage(self):
        allocation = self._allocation(
            sale_price_snapshot=2209581.1,
            escrow_pct=25.86,
            allocated_amount=571491.43,
        )
        self.assertAlmostEqual(
            allocation.required_amount,
            2209581.1 * 0.2586, places=2,
        )
        self.assertAlmostEqual(
            allocation.variance_amount,
            571491.43 - 2209581.1 * 0.2586, places=2,
        )

    def test_matching_allocation_has_no_variance(self):
        allocation = self._allocation(
            sale_price_snapshot=1000000.0,
            escrow_pct=10.0,
            allocated_amount=100000.0,
        )
        self.assertAlmostEqual(allocation.variance_amount, 0.0, places=2)
        self.assertTrue(allocation.has_source_data)

    def test_under_allocation_is_negative_variance(self):
        allocation = self._allocation(
            sale_price_snapshot=1000000.0,
            escrow_pct=10.0,
            allocated_amount=60000.0,
        )
        self.assertAlmostEqual(allocation.variance_amount, -40000.0, places=2)

    def test_over_allocation_is_positive_variance(self):
        """The BR1/408 pattern: more in escrow than the rules require."""
        allocation = self._allocation(
            sale_price_snapshot=1511739.0,
            escrow_pct=18.1,
            allocated_amount=335630.0,
        )
        self.assertGreater(allocation.variance_amount, 0.0)

    # -- Absent stays absent ---
    def test_missing_allocation_is_unknown_not_zero(self):
        # "No figure on file" is expressed as None -- an explicit 0.0 in the
        # source is a *supplied* figure (see test_explicit_zero below).
        allocation = self._allocation(
            sale_price_snapshot=1000000.0,
            escrow_pct=10.0,
            allocated_amount=None,
        )
        self.assertFalse(allocation.has_source_data)
        self.assertAlmostEqual(allocation.allocated_amount, 0.0, places=2)
        # Critically: no variance is asserted against a figure nobody supplied.
        self.assertAlmostEqual(allocation.variance_amount, 0.0, places=2)
        # But the requirement is still computed, so the gap is visible.
        self.assertAlmostEqual(allocation.required_amount, 100000.0, places=2)

    def test_explicit_zero_is_a_supplied_figure(self):
        # The register's BR2/512 pattern: the source states exactly 0.00
        # allocated. That is a fact, so it belongs in the under-allocation
        # bucket with the full shortfall as its variance.
        allocation = self._allocation(
            sale_price_snapshot=1000000.0,
            escrow_pct=10.0,
            allocated_amount=0.0,
        )
        self.assertTrue(allocation.has_source_data)
        self.assertAlmostEqual(allocation.required_amount, 100000.0, places=2)
        self.assertAlmostEqual(allocation.variance_amount, -100000.0, places=2)

    def test_awaiting_source_count_excludes_them_from_allocated_totals(self):
        # Two units: one row per (project, unit) is the database's rule, so the
        # second row needs its own unit (one supplied, one not).
        other = self.create_unit(self.project, '102')
        other_contract = self.create_contract(
            other, self.buyer, sale_price=1000000.0)
        self._allocation(
            sale_price_snapshot=1000000.0, escrow_pct=10.0, allocated_amount=100000.0)
        self._allocation(
            unit_id=other.id, contract_id=other_contract.id,
            sale_price_snapshot=1000000.0, escrow_pct=10.0, allocated_amount=None)
        self.project.invalidate_recordset()
        self.assertEqual(self.project.escrow_allocation_count, 2)
        self.assertEqual(self.project.escrow_allocation_pending_count, 1)
        self.assertAlmostEqual(
            self.project.escrow_allocation_allocated_amount, 100000.0, places=2)

    # -- Guards ---
    def test_percentage_out_of_range_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._allocation(sale_price_snapshot=1000000.0, escrow_pct=120.0)
        with self.assertRaises(ValidationError):
            self._allocation(sale_price_snapshot=1000000.0, escrow_pct=-5.0)

    def test_negative_allocation_is_rejected(self):
        with self.assertRaises(ValidationError):
            self._allocation(
                sale_price_snapshot=1000000.0, escrow_pct=10.0, allocated_amount=-1.0)

    def test_unit_from_another_project_is_rejected(self):
        other = self.setup_project(code='SGCB')
        foreign_unit = self.create_unit(other, '999')
        with self.assertRaises(ValidationError):
            self._allocation(unit_id=foreign_unit.id)

    def test_duplicate_unit_in_one_project_is_refused_by_the_database(self):
        self._allocation()
        with self.assertRaises(Exception):
            self._allocation()

    def test_partner_defaults_from_the_contract(self):
        allocation = self._allocation(sale_price_snapshot=1000000.0, escrow_pct=10.0)
        self.assertEqual(allocation.partner_id, self.buyer)


class TestEscrowAllocationImport(EscrowCommon):
    """The importer that absorbs the deferred 226-unit escrow ledger."""

    def setUp(self):
        super().setUp()
        self.project = self.setup_project(code='SGCI')
        self.unit = self.create_unit(self.project, '101', sale_price=2209581.1)

    def _upload(self, records, flags=None, dry_run=True):
        wizard = self.env['escrow.allocation.import'].create({
            'source_file': base64.b64encode(
                json.dumps(records).encode('utf-8')),
            'source_filename': 'escrow_deferred.json',
            'dry_run': dry_run,
        })
        if flags is not None:
            wizard.flag_file = base64.b64encode(json.dumps(flags).encode('utf-8'))
            wizard.flag_filename = 'flags.json'
        return wizard

    def _deferred_row(self, **overrides):
        row = {
            'project': self.project.code,
            'unit': self.unit.unit_number,
            'client': 'MACHIEL DE VRIES',
            'escrow_pct': 0.2586424322,
            'escrow_allocated': 571491.43,
            'sold': 2209581.1,
            'collected': 867736.93,
        }
        row.update(overrides)
        return row

    def test_fraction_percentage_is_stored_as_a_percentage(self):
        wizard = self._upload([self._deferred_row()], dry_run=False)
        wizard.action_run()

        allocation = self.env['escrow.allocation'].search([
            ('unit_id', '=', self.unit.id),
        ])
        self.assertEqual(len(allocation), 1)
        self.assertAlmostEqual(allocation.escrow_pct, 25.86, places=2)
        self.assertAlmostEqual(allocation.sale_price_snapshot, 2209581.1, places=2)
        self.assertAlmostEqual(allocation.collected_amount, 867736.93, places=2)
        self.assertAlmostEqual(allocation.allocated_amount, 571491.43, places=2)

    def test_missing_allocation_imports_as_unknown(self):
        wizard = self._upload(
            [self._deferred_row(escrow_allocated=None)], dry_run=False)
        wizard.action_run()

        allocation = self.env['escrow.allocation'].search([
            ('unit_id', '=', self.unit.id),
        ])
        self.assertFalse(allocation.has_source_data)

    def test_reimport_updates_rather_than_duplicates(self):
        self._upload([self._deferred_row()], dry_run=False).action_run()
        second = self._upload(
            [self._deferred_row(collected=900000.0)], dry_run=False)
        second.action_run()

        allocations = self.env['escrow.allocation'].search([
            ('unit_id', '=', self.unit.id),
        ])
        self.assertEqual(len(allocations), 1)
        self.assertAlmostEqual(allocations.collected_amount, 900000.0, places=2)
        self.assertEqual(second.created_count, 0)
        self.assertEqual(second.updated_count, 1)

    def test_dry_run_writes_nothing(self):
        wizard = self._upload([self._deferred_row()], dry_run=True)
        wizard.action_run()
        self.assertEqual(
            self.env['escrow.allocation'].search_count([('unit_id', '=', self.unit.id)]),
            0,
        )
        self.assertEqual(wizard.created_count, 1)

    def test_unresolvable_unit_is_reported_not_guessed(self):
        wizard = self._upload(
            [self._deferred_row(unit='NOT-A-UNIT')], dry_run=False)
        wizard.action_run()
        self.assertEqual(wizard.skipped_count, 1)
        self.assertEqual(wizard.created_count, 0)
        self.assertEqual(
            self.env['escrow.allocation'].search_count([('unit_id', '=', self.unit.id)]),
            0,
        )

    def test_flags_are_stamped_on_the_matching_unit(self):
        flags = [{
            'kind': 'OVERPAYMENT',
            'project': self.project.code,
            'unit': self.unit.unit_number,
            'info': 'balance due negative (-68619.12); verify overpayment',
        }]
        wizard = self._upload([self._deferred_row()], flags=flags, dry_run=False)
        wizard.action_run()

        allocation = self.env['escrow.allocation'].search([
            ('unit_id', '=', self.unit.id),
        ])
        self.assertEqual(allocation.flag_code, 'OVERPAYMENT')
        self.assertTrue(allocation.flag_note)
        self.assertTrue(allocation.reconciliation_note)

    def test_flagged_rows_are_counted_on_the_project(self):
        flags = [{
            'kind': 'BREAKDOWN_EXCEEDS_COLLECTED',
            'project': self.project.code,
            'unit': self.unit.unit_number,
            'info': 'a10 exceeds collected',
        }]
        self._upload([self._deferred_row()], flags=flags, dry_run=False).action_run()
        self.project.invalidate_recordset()
        self.assertEqual(self.project.escrow_allocation_flag_count, 1)

    def test_csv_input_is_accepted(self):
        import csv
        import io
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=[
            'project', 'unit', 'client', 'escrow_pct',
            'escrow_allocated', 'sold', 'collected'])
        writer.writeheader()
        writer.writerow(self._deferred_row())
        wizard = self.env['escrow.allocation.import'].create({
            'source_file': base64.b64encode(buffer.getvalue().encode('utf-8')),
            'source_filename': 'escrow.csv',
            'dry_run': False,
        })
        wizard.action_run()
        self.assertEqual(
            self.env['escrow.allocation'].search_count([('unit_id', '=', self.unit.id)]),
            1,
        )