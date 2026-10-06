from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import EoiCommon


@tagged('post_install', '-at_install', 'sgc_eoi')
class TestEoiWorkflow(EoiCommon):

    def booked(self, eoi_amount=50000.0):
        eoi = self.new_eoi(amount=eoi_amount)
        eoi.action_confirm()
        eoi.action_convert_to_booking()
        return eoi, eoi.booking_id

    # 1
    def test_01_available_to_eoi(self):
        unit = self.new_unit()
        self.assertEqual(unit.state, 'available')
        eoi = self.new_eoi(unit)
        self.assertEqual(unit.state, 'available', 'A draft EOI does not hold the unit')
        eoi.action_confirm()
        self.assertEqual(eoi.state, 'active')
        self.assertEqual(unit.state, 'eoi')
        self.assertFalse(unit.booking_ids, 'EOI is not a booking')
        with self.assertRaises(UserError):
            self.new_eoi(unit).action_confirm()

    # 2
    def test_02_eoi_cancel_releases_unit(self):
        unit = self.new_unit()
        eoi = self.new_eoi(unit)
        eoi.action_confirm()
        eoi.action_cancel('Customer changed mind')
        self.assertEqual(eoi.state, 'cancelled')
        self.assertEqual(unit.state, 'available')
        self.assertEqual(eoi.contract_id.state, 'cancelled')
        self.assertEqual(eoi.cancel_reason, 'Customer changed mind')
        self.assertTrue(eoi.cancel_date)
        self.assertEqual(eoi.cancel_user_id, self.env.user)
        # the unit can be reserved again
        self.new_eoi(unit).action_confirm()
        self.assertEqual(unit.state, 'eoi')

    # 3
    def test_03_eoi_to_booked_preserves_data(self):
        eoi = self.new_eoi(amount=50000)
        eoi.action_confirm()
        self.pay(eoi, 50000)
        self.assertEqual(eoi.payment_state, 'paid')
        contract = eoi.contract_id
        eoi.action_convert_to_booking()
        booking = eoi.booking_id
        self.assertEqual(eoi.state, 'converted')
        self.assertEqual(eoi.property_id.state, 'booked')
        self.assertEqual(booking.state, 'confirmed')
        self.assertEqual(booking.eoi_id, eoi)
        self.assertEqual(booking.payment_ids, eoi.payment_ids, 'EOI payment carries over')
        self.assertEqual(booking.booking_paid_amount, 50000)
        self.assertEqual(booking.sale_contract_id, contract, 'same contract, no duplicate')
        self.assertEqual(self.env['sale.contract'].search_count([('property_id', '=', eoi.property_id.id)]), 1)
        self.assertEqual(self.env['account.payment'].search_count([('id', 'in', eoi.payment_ids.ids)]), 1)
        with self.assertRaises(UserError):
            eoi.action_convert_to_booking()
        with self.assertRaises(UserError):
            eoi.action_cancel('x')          # converted EOI is cancelled through its booking

    # 4
    def test_04_booked_without_payment_cannot_confirm(self):
        _eoi, booking = self.booked(eoi_amount=0)
        self.assertGreater(booking.booking_amount, 0)
        with self.assertRaises(UserError):
            booking.action_confirm_sale()
        self.assertFalse(booking.sale_confirmed)
        self.assertEqual(booking.property_id.state, 'booked')
        # a manual flag no longer satisfies the gate
        booking.write({'payment_recorded': True, 'payment_amount': booking.booking_amount})
        with self.assertRaises(UserError):
            booking.action_confirm_sale()
        # partial payment is not enough
        self.pay(booking, booking.booking_amount / 2)
        with self.assertRaises(UserError):
            booking.action_confirm_sale()

    # 5
    def test_05_booked_with_verified_payment_confirms(self):
        _eoi, booking = self.booked(eoi_amount=0)
        self.pay(booking, booking.booking_amount)
        self.assertTrue(booking.payment_verified)
        booking.action_confirm_sale()
        self.assertTrue(booking.sale_confirmed)
        self.assertEqual(booking.property_id.state, 'confirmed_sale')
        self.assertEqual(booking.sale_contract_id.state, 'confirmed')

    # 6
    def test_06_smart_button(self):
        unit = self.new_unit()
        self.assertEqual(unit.eoi_count, 0)
        a = self.new_eoi(unit)
        a.action_confirm()
        a.action_cancel('r')
        b = self.new_eoi(unit)
        b.action_confirm()
        unit.invalidate_recordset()
        self.assertEqual(unit.eoi_count, 2)
        self.assertEqual(unit.active_eoi_id, b)
        action = unit.action_view_eois()
        self.assertEqual(action['res_model'], 'property.eoi')
        self.assertEqual(set(self.env['property.eoi'].search(action['domain']).ids), {a.id, b.id})

    # 7
    def test_07_contract_eoi_stage(self):
        eoi = self.new_eoi()
        eoi.action_confirm()
        self.assertEqual(eoi.contract_id.state, 'eoi')
        self.assertEqual(eoi.contract_id.eoi_id, eoi)
        with self.assertRaises(UserError):
            eoi.contract_id.action_sign()
        with self.assertRaises(UserError):
            eoi.contract_id.action_issue_spa()

    # 8
    def test_08_contract_booked_stage(self):
        eoi, booking = self.booked()
        self.assertEqual(eoi.contract_id.state, 'booked')
        self.assertEqual(eoi.contract_id.booking_id, booking)
        with self.assertRaises(UserError):
            eoi.contract_id.action_issue_spa()

    # 9
    def test_09_spa_workflow(self):
        _eoi, booking = self.booked(eoi_amount=0)
        self.pay(booking, booking.booking_amount)
        booking.action_confirm_sale()
        contract = booking.sale_contract_id
        with self.assertRaises(UserError):
            contract.action_sign()          # cannot sign before the SPA is issued
        contract.action_issue_spa()
        self.assertEqual(contract.state, 'spa_issued')
        contract.action_sign()
        self.assertEqual(contract.state, 'signed')
        self.assertEqual(booking.property_id.state, 'confirmed_sale')

    # 10
    def test_10_cancellation_cannot_release_confirmed_sale(self):
        _eoi, booking = self.booked(eoi_amount=0)
        self.pay(booking, booking.booking_amount)
        booking.action_confirm_sale()
        unit, contract = booking.property_id, booking.sale_contract_id
        with self.assertRaises(UserError):
            booking.action_cancel()
        with self.assertRaises(UserError):
            contract.action_cancel()
        with self.assertRaises(UserError):
            unit.write({'state': 'available'})
        with self.assertRaises(UserError):
            _eoi.action_cancel('x')
        self.assertEqual(unit.state, 'confirmed_sale')
        # the one proper route: manager + reason
        with self.assertRaises(UserError):
            booking._sgc_cancel_confirmed_sale('  ')
        with self.assertRaises(UserError):  # an officer is not enough
            booking.with_user(self.officer)._sgc_cancel_confirmed_sale('officer attempt')
        booking.with_user(self.manager)._sgc_cancel_confirmed_sale('Buyer defaulted - approved by management')
        self.assertEqual(unit.state, 'available')
        self.assertEqual(contract.state, 'cancelled')
        self.assertTrue(booking.payment_ids, 'payments are untouched')

    # 11 (HTML/QWeb leg; the wkhtmltopdf leg is in test_eoi_pdf.py)
    def test_11_pdf_generation(self):
        eoi = self.new_eoi(partner_id=self.customer.id)
        eoi.action_confirm()
        _e, booking = self.booked()
        for xmlid, rec in (('sgc_property_eoi.action_report_property_eoi', eoi),
                           ('sgc_property_eoi.action_report_booking_confirmation', booking)):
            report = self.env.ref(xmlid)
            html = report._render_qweb_html(xmlid_or_id(report), rec.ids)[0].decode()
            self.assertIn('EXPRESSION OF INTEREST' if rec._name == 'property.eoi' else 'PROPERTY BOOKING CONFIRMATION', html)
            self.assertIn(rec.name, html)
            self.assertNotIn('Traceback', html)


def xmlid_or_id(report):
    return report.report_name


@tagged('post_install', '-at_install', 'sgc_eoi')
class TestEoiRegression(EoiCommon):

    def test_legacy_state_keys_preserved(self):
        unit_keys = {k for k, _l in self.env['property.details']._fields['state'].selection}
        self.assertTrue({'available', 'booked', 'sold', 'rented', 'maintenance'} <= unit_keys)
        self.assertTrue({'eoi', 'confirmed_sale'} <= unit_keys)
        contract_keys = {k for k, _l in self.env['sale.contract']._fields['state'].selection}
        self.assertTrue({'draft', 'signed', 'completed', 'cancelled'} <= contract_keys)
        self.assertTrue({'eoi', 'booked', 'confirmed', 'spa_issued'} <= contract_keys)

    def test_legacy_booking_without_eoi_still_works(self):
        unit = self.new_unit()
        booking = self.env['property.vendor'].create({
            'vendor_id': self.customer.id, 'customer_id': self.customer.id, 'property_id': unit.id,
            'sale_price': 1500000.0})
        booking.action_confirm()
        self.assertEqual(unit.state, 'booked')
        with self.assertRaises(UserError):
            booking.action_confirm_sale()      # hard gate: no verified payment
        self.pay(booking, booking.booking_amount)
        booking.action_confirm_sale()
        self.assertEqual(unit.state, 'confirmed_sale')
        self.assertEqual(booking.sale_contract_id.state, 'confirmed')

    def test_handover_completes_to_sold(self):
        eoi = self.new_eoi(amount=0)
        eoi.action_confirm()
        eoi.action_convert_to_booking()
        booking = eoi.booking_id
        self.pay(booking, booking.booking_amount)
        booking.action_confirm_sale()
        contract = booking.sale_contract_id
        contract.action_issue_spa()
        contract.action_sign()
        contract.action_complete()
        self.assertEqual(booking.property_id.state, 'sold')

    def test_eoi_cancel_never_releases_booked_unit(self):
        eoi = self.new_eoi()
        eoi.action_confirm()
        eoi.action_convert_to_booking()
        with self.assertRaises(UserError):
            eoi.action_cancel('x')
        self.assertEqual(eoi.property_id.state, 'booked')

    def test_unit_state_guard(self):
        unit = self.new_unit()
        with self.assertRaises(UserError):
            unit.write({'state': 'confirmed_sale'})   # not from Available
        eoi = self.new_eoi(unit)
        eoi.action_confirm()
        with self.assertRaises(UserError):
            unit.write({'state': 'confirmed_sale'})   # not from EOI either

    def test_eoi_expiry_cron(self):
        from datetime import timedelta
        from odoo import fields
        unit = self.new_unit()
        eoi = self.new_eoi(unit, eoi_date=fields.Datetime.now() - timedelta(days=10),
                           valid_until=fields.Date.today() - timedelta(days=1))
        with self.assertRaises(Exception):
            self.new_eoi(self.new_unit(), valid_until=fields.Date.today() - timedelta(days=30))
        eoi.action_confirm()
        with self.assertRaises(UserError):
            eoi.action_convert_to_booking()
        self.env['property.eoi']._cron_expire_eois()
        self.assertEqual(eoi.state, 'expired')
        self.assertEqual(unit.state, 'available')

    def test_officer_sees_only_linked_payments(self):
        eoi = self.new_eoi()
        eoi.action_confirm()
        self.pay(eoi, 1000)
        stray = self.env['account.payment'].create({
            'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': self.customer.id,
            'amount': 5, 'journal_id': self.journal.id})
        visible = self.env['account.payment'].with_user(self.officer).search(
            [('id', 'in', (eoi.payment_ids | stray).ids)])
        self.assertEqual(visible, eoi.payment_ids)
        self.assertEqual(eoi.with_user(self.officer).amount_paid, 1000)
        with self.assertRaises(Exception):
            eoi.payment_ids.with_user(self.officer).write({'memo': 'tamper'})

    def test_dashboard_extra_keys(self):
        unit = self.new_unit()
        eoi = self.new_eoi(unit)
        eoi.action_confirm()
        stats = self.env['property.details'].get_property_stats()
        self.assertGreaterEqual(stats['eoi_property'], 1)
        self.assertIn('confirmed_sale_property', stats)
        self.project.invalidate_recordset()
        self.assertEqual(self.project.eoi_unit_count, 1)

    def test_officer_can_run_the_payment_wizards(self):
        """Regression for a UI-found defect: the wizards ran as the sales officer, who has no accounting rights."""
        eoi = self.new_eoi(amount=1000).with_user(self.officer)
        eoi.action_confirm()
        wiz = self.env['property.eoi.payment.wizard'].with_user(self.officer).create({
            'eoi_id': eoi.id, 'amount': 1000, 'journal_id': self.journal.id, 'payment_mode': 'cheque'})
        wiz.action_record()
        self.assertEqual(eoi.amount_paid, 1000)
        eoi.action_convert_to_booking()
        booking = eoi.booking_id
        left = booking.booking_amount - booking.booking_paid_amount
        wiz = self.env['sale.record.payment.wizard'].with_user(self.officer).create({
            'booking_id': booking.id, 'payment_amount': left, 'journal_id': self.journal.id})
        wiz.action_record()
        booking = booking.with_user(self.officer)
        self.assertTrue(booking.payment_verified)
        booking.action_confirm_sale()
        self.assertEqual(booking.property_id.state, 'confirmed_sale')
