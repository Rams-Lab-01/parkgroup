# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Field-mapping tests per runbook section 8.3/8.4 — confirm the new
res.partner and account.move fields exist, hold the right values, and
that the computed uae_is_credit_note / transaction_type_flags fields
stay in sync with their sources.
"""

from odoo.tests.common import TransactionCase


class TestPintAeFieldMapping(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.supplier = cls.env["res.partner"].create({
            "name": "Test Supplier LLC",
            "trn": "100123456700003",
            "legal_registration_id": "CN-1234567",
            "legal_registration_type": "TL",
        })
        cls.buyer = cls.env["res.partner"].create({
            "name": "Test Buyer LLC",
            "trn": "100987654300003",
        })
        cls.doc_type_380 = cls.env.ref(
            "uae_einvoice_core.doc_type_380_tax_invoice"
        )
        cls.doc_type_381 = cls.env.ref(
            "uae_einvoice_core.doc_type_381_tax_credit_note"
        )
        # test company has no chart of accounts installed (ran with
        # --without-demo=all), so account.move needs an explicit sales
        # journal or _search_default_journal() raises UserError.
        if not cls.env["account.journal"].search(
            [("type", "=", "sale"), ("company_id", "=", cls.env.company.id)]
        ):
            cls.env["account.journal"].create({
                "name": "Test Sales Journal",
                "type": "sale",
                "code": "TSALE",
                "company_id": cls.env.company.id,
            })

    def test_partner_fields_round_trip(self):
        self.assertEqual(self.supplier.trn, "100123456700003")
        self.assertEqual(self.supplier.legal_registration_type, "TL")
        self.assertEqual(self.supplier.peppol_scheme_id, "0235")

    def test_peppol_scheme_id_default(self):
        p = self.env["res.partner"].create({"name": "No override"})
        self.assertEqual(p.peppol_scheme_id, "0235")

    def test_document_type_seed_data_loaded(self):
        self.assertEqual(self.doc_type_380.code, "380")
        self.assertFalse(self.doc_type_380.is_credit_note)
        self.assertEqual(self.doc_type_381.code, "381")
        self.assertTrue(self.doc_type_381.is_credit_note)

    def test_move_uae_is_credit_note_follows_document_type(self):
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.buyer.id,
            "uae_document_type_id": self.doc_type_380.id,
        })
        self.assertFalse(move.uae_is_credit_note)

        move.uae_document_type_id = self.doc_type_381.id
        self.assertTrue(move.uae_is_credit_note)

    def test_transaction_type_flags_related_field_syncs(self):
        tx_type = self.env["uae.einvoice.transaction.type"].create({
            "name": "test-move-flags",
            "profile_execution_id": 0x03,  # FTZ + Deemed
        })
        move = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.buyer.id,
            "uae_transaction_type_id": tx_type.id,
        })
        self.assertEqual(move.transaction_type_flags, 0x03)

        tx_type.profile_execution_id = 0x80
        move.invalidate_recordset()
        self.assertEqual(move.transaction_type_flags, 0x80)

    def test_endpoint_seed_data_loaded(self):
        endpoint = self.env.ref(
            "uae_einvoice_core.endpoint_9900000097_deemed_supply"
        )
        self.assertEqual(endpoint.scheme_id, "0235")
        self.assertEqual(endpoint.identifier, "9900000097")
        self.assertEqual(endpoint.purpose, "deemed_supply")
