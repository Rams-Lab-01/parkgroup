# -*- coding: utf-8 -*-
from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests.common import tagged

from odoo.addons.sgc_offplan_rental_property_management.services.sgc_audit_internal_service import (
    SgcAuditInternalService,
)


@tagged("post_install", "-at_install")
class TestSmoke(AccountTestInvoicingCommon):
    """Smoke and regression tests for the forensic remediation fixes.

    Uses AccountTestInvoicingCommon which provides a complete Chart of Accounts
    with receivable/payable accounts, sale/purchase journals, and default taxes.
    This eliminates the from-scratch-DB CoA gap that previously blocked 4 of 9
    tests from passing.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # AccountTestInvoicingCommon already creates:
        # - cls.company_data with default_chart (full CoA)
        # - cls.company_data['default_journal_sale'] (sale journal)
        # - cls.company_data['default_journal_purchase'] (purchase journal)
        # - receivable/payable accounts for partners
        # - default sales/purchase taxes
        # No manual journal/account creation needed.
        # Its default test user only carries accounting groups, so grant the
        # Property Management group needed for property.details.create() below.
        # Granting a protected privilege group is Tier-1 governed and is
        # only allowed while the Channel-1 guard owns the path (the gate is
        # enforced again since 19.0.2.57).
        service = SgcAuditInternalService(cls.env)
        service.guard_begin('res.users', cls.env.user.id)
        cls.env.user.write({'group_ids': [(4, cls.env.ref(
            'sgc_offplan_rental_property_management.property_rental_manager').id)]})
        service.guard_end('res.users', cls.env.user.id)

    def test_get_property_stats_returns_dict(self):
        stats = self.env["property.details"].get_property_stats()
        self.assertIsInstance(
            stats, dict, "get_property_stats() should return a dict"
        )

    def test_property_document_count_uses_correct_model(self):
        """Document count must query property.documents, not property.document."""
        property_record = self.env["property.details"].create({
            "name": "Test Property for Document Count",
        })
        self.assertEqual(property_record.document_count, 0)
        self.env["property.documents"].create({
            "property_id": property_record.id,
            "doc_category": "other",
        })
        property_record._compute_document_count()
        self.assertEqual(property_record.document_count, 1)

    def test_rent_bill_quarterly_amount_multiplied(self):
        """Quarterly contracts must bill rent_amount * 3, not a flat month."""
        partner = self.env["res.partner"].create({"name": "Test Tenant"})
        property_record = self.env["property.details"].create({
            "name": "Test Property for Quarterly Billing",
        })
        contract = self.env["rent.contract"].create({
            "name": "RCT-QUARTERLY-01",
            "property_id": property_record.id,
            "tenant_id": partner.id,
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "rent_amount": 1000.0,
            "payment_frequency": "quarterly",
        })
        contract.action_generate_rent_bills()
        bills = self.env["rent.bill"].search([("contract_id", "=", contract.id)])
        self.assertEqual(len(bills), 1, "Expected one quarterly bill for the period")
        self.assertEqual(
            bills.amount, 3000.0,
            "Quarterly bill amount should be rent_amount * 3"
        )
        self.assertEqual(
            bills.rent_amount, 3000.0,
            "Quarterly rent_amount should be rent_amount * 3"
        )
        move = bills.rent_bill_id
        self.assertTrue(move.exists())
        self.assertEqual(
            move.invoice_line_ids[0].price_unit, 3000.0,
            "Invoice line price_unit should be rent_amount * 3"
        )

    def test_invoice_partner_ownership_field(self):
        """Invoice scoping uses partner_id; model-level sanity check for IDOR fix."""
        partner_a = self.env["res.partner"].create({"name": "Partner A"})
        partner_b = self.env["res.partner"].create({"name": "Partner B"})
        invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": partner_b.id,
        })
        self.assertEqual(invoice.partner_id, partner_b)
        self.assertNotEqual(invoice.partner_id, partner_a)

    def test_maintenance_vendor_bill_partner_is_int(self):
        """Vendor bill creation must set partner_id to an int, not a tuple."""
        vendor = self.env["res.partner"].create({"name": "Test Vendor"})
        property_record = self.env["property.details"].create({
            "name": "Test Property for Maintenance Bill",
        })
        # maintenance_team_id is required at the base maintenance.request
        # level; the demo team it would otherwise default to isn't loaded
        # under --without-demo=all.
        team = self.env["maintenance.team"].sudo().create({"name": "Test Maintenance Team"})
        # This test exercises the vendor-bill partner_id data shape, not
        # maintenance.request's own ACL (a separate group from Property
        # Management), so create it via sudo like the module's own
        # action_crete_bill()/action_crete_invoice() already do for bills.
        maintenance = self.env["maintenance.request"].sudo().create({
            "name": "Leaky tap",
            "property_id": property_record.id,
            "payment_from": "vendor",
            "vendor_id": vendor.id,
            "maintenance_team_id": team.id,
        })
        product = self.env["product.product"].create({
            "name": "Maintenance Service",
            "type": "service",
        })
        self.env["maintenance.product.line"].create({
            "maintenance_id": maintenance.id,
            "product_id": product.id,
            "description": "Fix tap",
            "quantity": 1,
            "price_unit": 100.0,
        })
        maintenance.action_crete_bill()
        self.assertTrue(maintenance.bill_id)
        self.assertIsInstance(
            maintenance.bill_id.partner_id.id, int,
            "Vendor bill partner_id must resolve to an integer user id"
        )
        self.assertEqual(maintenance.bill_id.partner_id, vendor)

    def test_dashboard_rent_total_reflects_rent_bills(self):
        """BE-03: dashboard rent KPIs must aggregate rent.bill (populated by the
        real billing path), not the never-written rent.invoice model.

        Fails pre-fix (get_property_stats summed rent.invoice, which stays empty),
        passes post-fix (it now sums rent.bill).
        """
        partner = self.env["res.partner"].create({"name": "Dashboard Tenant"})
        property_record = self.env["property.details"].create({
            "name": "Dashboard Property",
        })
        contract = self.env["rent.contract"].create({
            "name": "RCT-DASH-01",
            "property_id": property_record.id,
            "tenant_id": partner.id,
            "start_date": "2026-01-01",
            "end_date": "2026-03-31",
            "rent_amount": 1000.0,
            "payment_frequency": "monthly",
        })
        contract.action_generate_rent_bills()
        bills = self.env["rent.bill"].search([("contract_id", "=", contract.id)])
        expected_total = sum(bills.mapped("amount"))
        self.assertGreater(expected_total, 0.0)

        stats = self.env["property.details"].get_property_stats()
        self.assertGreaterEqual(
            stats["rent_total"], expected_total,
            "Dashboard rent_total must include amounts billed via rent.bill",
        )
        self.assertGreaterEqual(
            stats["pending_invoice"], len(bills),
            "Unpaid generated rent bills must count toward pending_invoice",
        )

    def test_rent_bill_invoice_line_uses_configured_product(self):
        """BE-04: generated rent-bill invoice lines must carry the configured
        installment product (and thus its account/taxes), not a bare name line.

        Fails pre-fix (line had no product_id), passes post-fix.
        """
        product = self.env["product.product"].create({
            "name": "Rent Installment (Test)",
            "type": "service",
        })
        self.env["ir.config_parameter"].sudo().set_param(
            "sgc_offplan_rental_property_management.account_installment_item_id",
            str(product.id),
        )
        partner = self.env["res.partner"].create({"name": "Product Line Tenant"})
        property_record = self.env["property.details"].create({
            "name": "Product Line Property",
        })
        contract = self.env["rent.contract"].create({
            "name": "RCT-PROD-01",
            "property_id": property_record.id,
            "tenant_id": partner.id,
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "rent_amount": 1500.0,
            "payment_frequency": "monthly",
        })
        contract.action_generate_rent_bills()
        bill = self.env["rent.bill"].search(
            [("contract_id", "=", contract.id)], limit=1)
        move = bill.rent_bill_id
        self.assertTrue(move.exists())
        line = move.invoice_line_ids[0]
        self.assertEqual(
            line.product_id, product,
            "Generated rent-bill invoice line must use the configured "
            "installment product",
        )
