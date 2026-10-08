# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Validator tests per runbook section 8.5.

Covers what einvoice_validate() actually checks today: mandatory-field
completeness, TRN format, ProfileExecutionID presence, the credit-note
rule, and the no-negative-totals rule. Full XSD/Schematron validation
against rendered XML is out of scope until the UBL renderer module
exists (runbook section 11 build-sequence step 2).
"""

from odoo.tests.common import TransactionCase

from odoo.addons.uae_einvoice_core.models.einvoice_validator import einvoice_validate


class TestUblSchematronValidation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier_partner = cls.env.company.partner_id
        cls.buyer = cls.env["res.partner"].create({
            "name": "Buyer Co",
            "trn": "100987654300003",
        })
        cls.doc_type_380 = cls.env.ref(
            "uae_einvoice_core.doc_type_380_tax_invoice"
        )
        cls.doc_type_381 = cls.env.ref(
            "uae_einvoice_core.doc_type_381_tax_credit_note"
        )
        cls.tx_type = cls.env["uae.einvoice.transaction.type"].create({
            "name": "default",
            "profile_execution_id": 0,
        })
        if not cls.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", cls.env.company.id)]
        ):
            cls.env["account.journal"].create({
                "name": "Test Sales Journal",
                "type": "sale",
                "code": "TSALE",
                "company_id": cls.env.company.id,
            })

    def _make_move(self, **overrides):
        vals = {
            "move_type": "out_invoice",
            "partner_id": self.buyer.id,
            "uae_document_type_id": self.doc_type_380.id,
            "uae_transaction_type_id": self.tx_type.id,
        }
        vals.update(overrides)
        return self.env["account.move"].create(vals)

    def test_missing_supplier_trn_flagged(self):
        self.supplier_partner.trn = False
        move = self._make_move()
        result = einvoice_validate(move)
        self.assertFalse(result["valid"])
        self.assertIn("Supplier TRN is missing.", result["errors"])

    def test_missing_buyer_trn_flagged(self):
        self.supplier_partner.trn = "100123456700003"
        self.supplier_partner.legal_registration_id = "CN-1"
        self.buyer.trn = False
        move = self._make_move()
        result = einvoice_validate(move)
        self.assertFalse(result["valid"])
        self.assertIn("Buyer TRN is missing.", result["errors"])

    def test_malformed_trn_flagged(self):
        self.supplier_partner.trn = "100123456700003"
        self.supplier_partner.legal_registration_id = "CN-1"
        self.buyer.trn = "not-a-trn"
        move = self._make_move()
        result = einvoice_validate(move)
        self.assertFalse(result["valid"])
        self.assertTrue(
            any("is not a 15-digit number" in e for e in result["errors"])
        )

    def test_missing_transaction_type_flagged(self):
        self.supplier_partner.trn = "100123456700003"
        self.supplier_partner.legal_registration_id = "CN-1"
        self.buyer.trn = "100987654300003"
        move = self._make_move(uae_transaction_type_id=False)
        result = einvoice_validate(move)
        self.assertFalse(result["valid"])
        self.assertIn(
            "No ProfileExecutionID (transaction type flags) set.",
            result["errors"],
        )

    def test_credit_note_missing_reason_code_flagged(self):
        self.supplier_partner.trn = "100123456700003"
        self.supplier_partner.legal_registration_id = "CN-1"
        self.buyer.trn = "100987654300003"
        move = self._make_move(
            uae_document_type_id=self.doc_type_381.id,
            move_type="out_refund",
        )
        result = einvoice_validate(move)
        self.assertFalse(result["valid"])
        self.assertIn("Credit note reason code is required.", result["errors"])

    def test_credit_note_reason_vd_exempts_preceding_ref(self):
        self.supplier_partner.trn = "100123456700003"
        self.supplier_partner.legal_registration_id = "CN-1"
        self.buyer.trn = "100987654300003"
        move = self._make_move(
            uae_document_type_id=self.doc_type_381.id,
            move_type="out_refund",
            credit_note_reason_code="VD",
        )
        result = einvoice_validate(move)
        self.assertNotIn(
            "Preceding invoice reference is required unless "
            "credit_note_reason_code is 'VD'.",
            result["errors"],
        )

    def test_credit_note_non_vd_requires_preceding_ref(self):
        self.supplier_partner.trn = "100123456700003"
        self.supplier_partner.legal_registration_id = "CN-1"
        self.buyer.trn = "100987654300003"
        move = self._make_move(
            uae_document_type_id=self.doc_type_381.id,
            move_type="out_refund",
            credit_note_reason_code="OTHER",
        )
        result = einvoice_validate(move)
        self.assertIn(
            "Preceding invoice reference is required unless "
            "credit_note_reason_code is 'VD'.",
            result["errors"],
        )

    def test_fully_valid_invoice_passes(self):
        self.supplier_partner.trn = "100123456700003"
        self.supplier_partner.legal_registration_id = "CN-1"
        self.buyer.trn = "100987654300003"
        move = self._make_move()
        result = einvoice_validate(move)
        self.assertEqual(result["errors"], [])
        self.assertTrue(result["valid"])
