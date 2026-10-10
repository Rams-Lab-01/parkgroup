# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError
from datetime import date


class TestEoiWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency_aed = cls.env.ref('base.AED', raise_if_not_found=False)
        if not cls.currency_aed:
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

    def test_02_eoi_cancellation_and_refund(self):
        """Test cancelling and refunding EOI returns unit to Available status."""
        # Create an EOI contract
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

    def test_04_full_contract_pipeline(self):
        """Test contract progression: Booked -> SPA Issued -> SPA Signed.

        The legacy 'confirmed' state was dropped; action_confirm_sale is now a
        deprecated shim that delegates to action_issue_spa, so the pipeline
        goes booked -> spa_issued -> spa_signed.
        """
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

        # Confirm Sale (deprecated shim -> SPA Issued)
        contract.action_confirm_sale()
        self.assertEqual(contract.state, 'spa_issued')
        self.assertTrue(contract.spa_issue_date)

        # Sign SPA -> Property transitions to Sold
        contract.action_sign_spa()
        self.assertEqual(contract.state, 'spa_signed')
        self.assertTrue(contract.spa_signed_date)
        self.assertEqual(self.property.state, 'sold', "Property should transition to Sold on SPA signed")

    def test_05_qweb_reports_rendering(self):
        """Verify both EOI Agreement and Reservation Form QWeb reports render without errors."""
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
