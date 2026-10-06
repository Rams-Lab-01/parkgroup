# -*- coding: utf-8 -*-
"""Totals-visibility regression (19.0.2.65).

Every multi-row amount table must show a clearly visible total at the
bottom: QWeb report money tables carry a tfoot/TOTAL row, and in-app
list views carry sum="Total" on amount columns so the list footer
renders the total row.
"""
import re

from odoo.tests.common import TransactionCase, tagged

MODULE = 'sgc_offplan_rental_property_management'


def _arch_has_sum(arch, field_name):
    """True if <field name="X" ... sum=...> occurs in the arch."""
    return re.search(r'<field\s+name="%s"[^>]*\bsum=' % re.escape(field_name), arch) is not None


@tagged('post_install', 'sgc_totals')
class TestTotalsVisibility(TransactionCase):

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _list_view_archs(self, model, marker):
        """Installed list view archs for `model` whose arch contains `marker`."""
        views = self.env['ir.ui.view'].search([
            ('model', '=', model),
            ('type', '=', 'list'),
        ])
        return [v for v in views if marker in (v.arch or '')]

    def _form_view_archs(self, model, marker):
        """Installed form view archs for `model` whose arch contains `marker`."""
        views = self.env['ir.ui.view'].search([
            ('model', '=', model),
            ('type', '=', 'form'),
        ])
        return [v for v in views if marker in (v.arch or '')]

    def _report_archs(self, marker):
        """QWeb report template archs (type='qweb') containing `marker`.
        Excludes portal views (keys containing 'portal')."""
        views = self.env['ir.ui.view'].search([
            ('type', '=', 'qweb'),
            ('arch_db', 'ilike', '%{}%'.format(marker)),
        ])
        # Filter out portal views
        return [v for v in views if 'portal' not in (v.key or '')]

    # ------------------------------------------------------------------
    # QWeb report templates: bottom total row present
    # ------------------------------------------------------------------
    def test_report_statement_of_account_has_total(self):
        archs = self._report_archs('Transaction History')
        self.assertTrue(archs, 'statement of account template not found')
        for v in archs:
            self.assertIn('<tfoot', v.arch, 'SOA transaction table lacks total row')
            self.assertIn("mapped('debit')", v.arch)
            self.assertIn("mapped('credit')", v.arch)

    def test_report_maintenance_contract_has_total(self):
        archs = self._report_archs('Product / Service Lines')
        self.assertTrue(archs, 'maintenance contract template not found')
        for v in archs:
            self.assertIn('<tfoot', v.arch, 'maintenance lines table lacks total row')
            self.assertIn('price_subtotal', v.arch.split('<tfoot')[-1])

    def test_report_portfolio_regional_total(self):
        archs = self._report_archs('Regional Distribution')
        self.assertTrue(archs, 'portfolio statistics template not found')
        for v in archs:
            self.assertIn('TOTAL', v.arch, 'regional distribution lacks TOTAL row')

    def test_report_project_summary_total(self):
        archs = self._report_archs('SGC Project Summary Report')
        self.assertTrue(archs, 'project summary template not found')
        for v in archs:
            self.assertIn('TOTAL', v.arch, 'property list lacks TOTAL row')

    def test_report_booking_agreement_total(self):
        archs = self._report_archs('Total (incl. Commission)')
        self.assertTrue(archs, 'booking agreement total row not found')
        for v in archs:
            self.assertIn('o.sale_price or 0.0', v.arch)

    def test_existing_report_totals_still_present(self):
        """Pre-existing bottom totals that must not regress."""
        self.assertTrue(self._report_archs('Total Scheduled'),
                        'SPA payment schedule total missing')
        self.assertTrue(self._report_archs('o_cs_lines'),
                        'commission summary template missing')
        self.assertTrue(self._report_archs('sale_contract_installment_plan_template'),
                        'installment plan template missing')
        spa = self._report_archs('Purchase Price (Reference)')
        self.assertTrue(spa, 'SPA purchase-price reference row missing')

    # ------------------------------------------------------------------
    # in-app list views: sum= on amount columns
    # ------------------------------------------------------------------
    def test_list_views_have_sum_totals(self):
        cases = [
            # (model, arch marker, fields that must carry sum=)
            ('sale.contract', 'Sale Contracts', ['sale_price']),
            ('property.details', 'Properties', ['price']),
            ('rera.form.a', 'RERA Form A', ['listing_price']),
            ('rent.contract', 'Rent Contracts', ['rent_amount']),
            ('rent.bill', 'Rent Invoice', ['amount']),
            ('rent.invoice', 'Rent Invoice', ['amount']),
            ('property.vendor', 'Bookings / Vendor Records', ['sale_price']),
        ]
        for model, marker, fields in cases:
            archs = self._list_view_archs(model, marker)
            self.assertTrue(archs, 'list view not found: %s / %s' % (model, marker))
            for v in archs:
                for fname in fields:
                    self.assertTrue(
                        _arch_has_sum(v.arch, fname),
                        '%s view (%s) field %s missing sum=' % (model, marker, fname),
                    )

    def test_form_line_views_have_sum_totals(self):
        """o2m line blocks in form views: commission lines, installments, bills, products."""
        cases = [
            ('sale.contract', 'commission_fixed_amount',
             ['commission_fixed_amount', 'commission_amount', 'amount_total', 'amount']),
            ('property.vendor', 'commission_fixed_amount',
             ['commission_fixed_amount', 'commission_amount', 'amount_total']),
            ('rent.contract', 'commission_fixed_amount',
             ['commission_fixed_amount', 'commission_amount', 'amount_total', 'amount']),
            ('maintenance.request', 'maintenance_product_ids', ['price_subtotal']),
            ('res.partner', 'property_sold_ids',
             ['sale_price', 'total_commission', 'total_rent']),
        ]
        for model, marker, fields in cases:
            archs = self._form_view_archs(model, marker)
            self.assertTrue(archs, 'form view not found: %s / %s' % (model, marker))
            for v in archs:
                for fname in fields:
                    self.assertTrue(
                        _arch_has_sum(v.arch, fname),
                        '%s view (%s) field %s missing sum=' % (model, marker, fname),
                    )