# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from datetime import date


class TestEoiWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The money is in the company's currency. Odoo ships most currencies
        # inactive (AED among them on a fresh database), and a payment cannot
        # be validated against an inactive currency.
        cls.currency_aed = cls.env.company.currency_id

        # Setup developer company partner
        cls.developer_partner = cls.env['res.partner'].create({
            'name': 'Park Residency Real Estate Development LLC',
            'is_company': True,
            'street': 'Office 323 & 325, Sultan Business Center, Oud Metha',
            'city': 'Dubai',
            'phone': '+971 4 222 9992',
            'email': 'contracts@parkgroup.sgctech.ai',
        })

        # Setup Buyer partner
        cls.buyer_partner = cls.env['res.partner'].create({
            'name': 'Mohammad Al Hashimi',
            'street': 'Villa 14, Al Safa 2, Jumeirah',
            'city': 'Dubai',
            'phone': '+971 50 123 4567',
                        'email': 'm.alhashimi@example.ae',
        })

        # Setup Joint Buyer partner
        cls.joint_buyer_partner = cls.env['res.partner'].create({
            'name': 'Fatima Al Hashimi',
            'street': 'Villa 14, Al Safa 2, Jumeirah',
            'city': 'Dubai',
            'phone': '+971 50 987 6543',
                        'email': 'fatima.hashimi@example.ae',
        })

        # Setup Property Project
        cls.project = cls.env['property.project'].create({
            'name': 'Park Golf Views',
            'code': 'PGV',

        })

        # Setup Property Details Unit
        cls.property = cls.env['property.details'].create({
            'name': 'PGV-304',
            'property_code': 'PGV-304',
            'project_id': cls.project.id,
            'owner_id': cls.developer_partner.id,
            'property_type': 'residential',
            'unit_type': '2br',
            'floor': 3,
            'area': 1450.0,
            'price': 1850000.0,
            'sale_price': 1850000.0,
            'sale_lease': 'sale',
            'currency_id': cls.currency_aed.id,
            'state': 'available',
        })

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _journal(self):
        journal = self.env['account.journal'].search([
            ('type', '=', 'bank'), ('company_id', '=', self.env.company.id)], limit=1)
        if not journal:
            journal = self.env['account.journal'].create({
                'name': 'Test Bank', 'code': 'TBK', 'type': 'bank',
                'company_id': self.env.company.id,
            })
        return journal

    def _register_receipt(self, unit=None, amount=50000.0):
        """Post a customer receipt and register it against the unit."""
        unit = unit or self.property
        return self.env['sgc.eoi.receipt.helper']._resolve_receipt(
            unit=unit,
            partner=self.buyer_partner,
            journal=self._journal(),
            amount=amount,
            date=date.today(),
            memo='EOI test receipt',
        )

    # ------------------------------------------------------------------
    # The money gate
    # ------------------------------------------------------------------
    def test_00_unit_cannot_move_to_eoi_without_a_receipt(self):
        """No posted receipt against the unit means no stage move."""
        with self.assertRaises(UserError):
            self.property.write({'state': 'eoi'})
        self.assertEqual(self.property.state, 'available')

    def test_00b_unit_moves_once_a_receipt_is_registered(self):
        receipt = self._register_receipt()
        self.assertEqual(receipt.state, 'in_process', "The receipt must be posted")
        self.assertEqual(receipt.property_id, self.property,
                         "The receipt must be registered against the unit")
        self.property.write({'state': 'eoi'})
        self.assertEqual(self.property.state, 'eoi')
        self.assertAlmostEqual(self.property.eoi_received_amount, 50000.0, places=2)

    def test_00c_confirm_sale_needs_a_posted_receipt(self):
        contract = self.env['sale.contract'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'seller_id': self.developer_partner.id,
            'sale_price': 1850000.0,
            'booking_amount': 185000.0,
            'currency_id': self.currency_aed.id,
            'state': 'booked',
        })
        with self.assertRaises(UserError):
            contract.action_confirm_sale()
        self._register_receipt()
        contract.action_confirm_sale()
        self.assertEqual(contract.state, 'confirmed')

    # ------------------------------------------------------------------
    # The workflow
    # ------------------------------------------------------------------
    def test_01_eoi_registration_via_wizard(self):
        """Test registering Expression of Interest (EOI) moves unit to EOI stage."""
        self.assertEqual(self.property.state, 'available', "Initial property state must be Available")

        wizard = self.env['eoi.registration.wizard'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'joint_buyer_id': self.joint_buyer_partner.id,
            'sale_price': self.property.sale_price,
            'currency_id': self.currency_aed.id,
            'eoi_amount': 50000.0,
            'payment_amount': 50000.0,
            'payment_date': date.today(),
            'journal_id': self._journal().id,
            'eoi_payment_mode': 'cheque',
            'eoi_cheque_no': 'CHQ-889921',
            'eoi_cheque_bank': 'Emirates NBD',
            'eoi_date': date.today(),
            'notes': 'Refundable within 7 days. CHQ held in escrow safe.',
        })
        action = wizard.action_register_eoi()
        self.assertTrue(action.get('res_id'), "Contract ID should be returned")

        contract = self.env['sale.contract'].browse(action['res_id'])
        self.assertEqual(self.property.state, 'eoi', "Property status should transition to 'eoi'")
        self.assertEqual(contract.state, 'eoi', "Contract status should be 'eoi'")
        self.assertEqual(contract.eoi_amount, 50000.0, "EOI amount should be 50,000 AED")
        self.assertEqual(contract.buyer_id, self.buyer_partner)
        self.assertEqual(contract.joint_buyer_id, self.joint_buyer_partner)
        self.assertEqual(self.property.eoi_count, 1, "EOI count should be 1")

        # The money is in Accounting, tied to the unit.
        self.assertEqual(len(contract.eoi_payment_ids), 1, "The receipt must be linked to the contract")
        receipt = contract.eoi_payment_ids
        self.assertIn(receipt.state, ('in_process', 'paid'), "The receipt must be posted")
        self.assertEqual(receipt.amount, 50000.0)
        self.assertEqual(receipt.property_id, self.property,
                         "The receipt must be registered against the unit")
        self.assertEqual(contract.eoi_receipt_state, 'paid')

    def test_01b_eoi_registration_links_an_existing_receipt(self):
        """A receipt already posted in Accounting can be used instead of a new one."""
        receipt = self._register_receipt()
        wizard = self.env['eoi.registration.wizard'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'sale_price': self.property.sale_price,
            'currency_id': self.currency_aed.id,
            'eoi_amount': 50000.0,
            'existing_payment_id': receipt.id,
            'eoi_payment_mode': 'bank_transfer',
            'eoi_date': date.today(),
        })
        action = wizard.action_register_eoi()
        contract = self.env['sale.contract'].browse(action['res_id'])
        self.assertEqual(self.property.state, 'eoi')
        self.assertEqual(contract.eoi_payment_ids, receipt)
        self.assertEqual(len(self.env['account.payment'].search([
            ('property_id', '=', self.property.id)])), 1,
            "The receipt must not be duplicated")

    def test_02_eoi_cancellation_and_refund(self):
        """Test cancelling and refunding EOI returns unit to Available status."""
        self._register_receipt()
        contract = self.env['sale.contract'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'seller_id': self.developer_partner.id,
            'sale_price': 1850000.0,
            'currency_id': self.currency_aed.id,
            'eoi_amount': 50000.0,
            'eoi_payment_mode': 'cheque',
            'state': 'eoi',
        })
        self.property.write({'state': 'eoi'})
        self.assertEqual(self.property.state, 'eoi')

        # Cancel EOI from property
        self.property.action_cancel_eoi()
        self.assertEqual(contract.state, 'refunded', "Contract should be marked Refunded")
        self.assertEqual(self.property.state, 'available', "Property should revert to Available")

    def test_03_convert_eoi_to_booked(self):
        """Test converting EOI to Booked stage upon receiving booking deposit."""
        self._register_receipt()
        contract = self.env['sale.contract'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'seller_id': self.developer_partner.id,
            'sale_price': 1850000.0,
            'currency_id': self.currency_aed.id,
            'eoi_amount': 50000.0,
            'eoi_payment_mode': 'cheque',
            'state': 'eoi',
        })
        self.property.write({'state': 'eoi'})

        # Convert to booked
        contract.write({'booking_amount': 185000.0})
        contract.action_convert_to_booked()

        self.assertEqual(contract.state, 'booked', "Contract should be Booked")
        self.assertEqual(self.property.state, 'booked', "Property should be Booked")
        self.assertTrue(contract.booking_date, "Booking date should be stamped")

    def test_03b_direct_booking_needs_a_receipt(self):
        """A booking without any money registered against the unit is refused."""
        wizard = self.env['eoi.to.booking.wizard'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'sale_price': self.property.sale_price,
            'currency_id': self.currency_aed.id,
            'booking_amount': 185000.0,
            'booking_date': date.today(),
        })
        with self.assertRaises(UserError):
            wizard.action_convert_to_booked()
        self.assertEqual(self.property.state, 'available')

    def test_03c_direct_booking_with_a_receipt(self):
        """A direct booking that posts its receipt goes through."""
        wizard = self.env['eoi.to.booking.wizard'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'sale_price': self.property.sale_price,
            'currency_id': self.currency_aed.id,
            'booking_amount': 185000.0,
            'booking_date': date.today(),
            'record_booking_receipt': True,
            'payment_amount': 185000.0,
            'payment_date': date.today(),
            'journal_id': self._journal().id,
        })
        wizard.action_convert_to_booked()
        self.assertEqual(self.property.state, 'booked')
        receipt = self.env['account.payment'].search([
            ('property_id', '=', self.property.id), ('state', 'in', ('in_process', 'paid'))], limit=1)
        self.assertTrue(receipt, "The booking receipt must be posted against the unit")
        self.assertEqual(receipt.amount, 185000.0)

    def test_04_full_contract_pipeline(self):
        """Test contract progression: Booked -> Confirmed -> SPA Issued -> SPA Signed."""
        self._register_receipt(amount=185000.0)
        contract = self.env['sale.contract'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'seller_id': self.developer_partner.id,
            'sale_price': 1850000.0,
            'booking_amount': 185000.0,
            'currency_id': self.currency_aed.id,
            'state': 'booked',
        })
        self.property.write({'state': 'booked'})

        # Confirm Sale
        contract.action_confirm_sale()
        self.assertEqual(contract.state, 'confirmed')

        # Issue SPA
        contract.action_issue_spa()
        self.assertEqual(contract.state, 'spa_issued')
        self.assertTrue(contract.spa_issue_date)

        # Sign SPA -> Property transitions to Sold
        contract.action_sign_spa()
        self.assertEqual(contract.state, 'spa_signed')
        self.assertTrue(contract.spa_signed_date)
        self.assertEqual(self.property.state, 'sold', "Property should transition to Sold on SPA signed")

    def test_03d_booking_payment_posts_a_receipt(self):
        """The booking "Record Payment" posts a real receipt against the unit."""
        booking = self.env['property.vendor'].create({
            'property_id': self.property.id,
            'vendor_id': self.developer_partner.id,
            'customer_id': self.buyer_partner.id,
            'sale_price': 1850000.0,
        })
        wizard = self.env['sale.record.payment.wizard'].create({
            'booking_id': booking.id,
            'payment_amount': 185000.0,
            'payment_date': date.today(),
            'journal_id': self._journal().id,
        })
        wizard.action_record()
        self.assertTrue(booking.payment_recorded, "The base flag must still be set")
        receipt = self.env['account.payment'].search([
            ('property_id', '=', self.property.id), ('state', 'in', ('in_process', 'paid'))], limit=1)
        self.assertTrue(receipt, "The booking receipt must be posted against the unit")
        self.assertEqual(receipt.amount, 185000.0)
        # With the money registered, the booking can move the unit.
        booking.action_confirm()
        self.assertEqual(self.property.state, 'booked')

    def test_04b_spa_needs_the_booking_amount_covered(self):
        """The booking amount is the basis for issuing the SPA for signing."""
        contract = self.env['sale.contract'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'seller_id': self.developer_partner.id,
            'sale_price': 1850000.0,
            'booking_amount': 185000.0,
            'currency_id': self.currency_aed.id,
            'state': 'confirmed',
        })
        self._register_receipt(amount=50000.0)
        self.assertFalse(contract.spa_eligible, "Half the booking amount is not enough")
        self.assertAlmostEqual(contract.spa_shortfall, 135000.0, places=2)
        with self.assertRaises(UserError):
            contract.action_issue_spa()

        self._register_receipt(amount=135000.0)
        contract.invalidate_recordset(['spa_eligible', 'spa_shortfall'])
        self.assertTrue(contract.spa_eligible, "The booking amount is now covered")
        contract.action_issue_spa()
        self.assertEqual(contract.state, 'spa_issued')

    def test_04c_spa_needs_a_booking_amount(self):
        """Without a booking amount there is no basis to issue the SPA."""
        contract = self.env['sale.contract'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'seller_id': self.developer_partner.id,
            'sale_price': 1850000.0,
            'currency_id': self.currency_aed.id,
            'state': 'confirmed',
        })
        self._register_receipt()
        with self.assertRaises(UserError):
            contract.action_issue_spa()

    def test_05_qweb_reports_rendering(self):
        """Verify both EOI Agreement and Reservation Form QWeb reports render without errors."""
        self._register_receipt()
        contract = self.env['sale.contract'].create({
            'property_id': self.property.id,
            'buyer_id': self.buyer_partner.id,
            'joint_buyer_id': self.joint_buyer_partner.id,
            'seller_id': self.developer_partner.id,
            'sale_price': 1850000.0,
            'eoi_amount': 50000.0,
            'eoi_payment_mode': 'cheque',
            'eoi_cheque_no': 'CHQ-00129',
            'eoi_cheque_bank': 'Abu Dhabi Commercial Bank',
            'booking_amount': 185000.0,
            'currency_id': self.currency_aed.id,
            'state': 'eoi',
        })
        self.property.write({'state': 'eoi'})

        # Test render EOI report
        eoi_pdf, _ = self.env['ir.actions.report']._render_qweb_pdf(
            'sgc_property_eoi_workflow.action_report_eoi_agreement',
            [contract.id],
        )
        self.assertTrue(len(eoi_pdf) > 0, "EOI agreement PDF should render content")

        # Test render Reservation Form report
        contract.action_convert_to_booked()
        res_pdf, _ = self.env['ir.actions.report']._render_qweb_pdf(
            'sgc_property_eoi_workflow.action_report_reservation_form',
            [contract.id],
        )
        self.assertTrue(len(res_pdf) > 0, "Reservation Form PDF should render content")
