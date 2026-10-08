# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Unit tests for the 8-bit ProfileExecutionID flag engine.

Source of truth is the ``profile_execution_id`` integer. The 8 boolean
fields are computed and stored from it. Caller is responsible for
keeping the integer in 0..255; the model itself does not mask.
"""

from odoo.tests.common import TransactionCase

from odoo.addons.uae_einvoice_core.models.uae_transaction_type import (
    UAETransactionType,
)


class TestFlagEngine(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Model = cls.env["uae.einvoice.transaction.type"]

    def test_all_flags_clear_round_trips_to_zero(self):
        rec = self.Model.create({"name": "none"})
        self.assertEqual(rec.profile_execution_id, 0)
        self.assertFalse(rec.flag_free_trade_zone)
        self.assertFalse(rec.flag_exports)

    def test_set_each_bit_via_integer(self):
        for bit, field_name in enumerate(UAETransactionType.FLAG_BIT_ORDER):
            rec = self.Model.create({
                "name": f"bit_{bit}",
                "profile_execution_id": 1 << bit,
            })
            with self.subTest(bit=bit, field=field_name):
                self.assertEqual(rec.profile_execution_id, 1 << bit)
                for other_bit, other_field in enumerate(
                    UAETransactionType.FLAG_BIT_ORDER
                ):
                    if other_bit == bit:
                        self.assertTrue(
                            getattr(rec, other_field),
                            f"bit {bit} ({other_field}) should be set",
                        )
                    else:
                        self.assertFalse(
                            getattr(rec, other_field),
                            f"bit {other_bit} ({other_field}) should NOT be set",
                        )

    def test_all_bits_set_via_integer(self):
        rec = self.Model.create({
            "name": "all",
            "profile_execution_id": 0xFF,
        })
        self.assertEqual(rec.profile_execution_id, 0xFF)
        for field_name in UAETransactionType.FLAG_BIT_ORDER:
            self.assertTrue(
                getattr(rec, field_name),
                f"{field_name} should be set when integer is 0xFF",
            )

    def test_specific_combinations(self):
        cases = [
            (0x01, ["flag_free_trade_zone"]),
            (0x02, ["flag_deemed_supply"]),
            (0x80, ["flag_exports"]),
            (0x11, ["flag_free_trade_zone", "flag_continuous_supply"]),
            (0xC0, ["flag_ecommerce", "flag_exports"]),
            (0x28, ["flag_summary_invoice", "flag_disclosed_agent"]),
            (0xA5, [
                "flag_free_trade_zone",
                "flag_profit_margin",
                "flag_disclosed_agent",
                "flag_exports",
            ]),
        ]
        for value, expected_set in cases:
            with self.subTest(value=value):
                rec = self.Model.create({
                    "name": f"combo_{value}",
                    "profile_execution_id": value,
                })
                for field_name in UAETransactionType.FLAG_BIT_ORDER:
                    if field_name in expected_set:
                        self.assertTrue(
                            getattr(rec, field_name),
                            f"{field_name} should be set for 0x{value:02X}",
                        )
                    else:
                        self.assertFalse(
                            getattr(rec, field_name),
                            f"{field_name} should NOT be set for 0x{value:02X}",
                        )

    def test_has_flag_helper(self):
        rec = self.Model.create({
            "name": "helper",
            "profile_execution_id": 0x82,
        })
        self.assertTrue(rec.has_flag("flag_deemed_supply"))
        self.assertTrue(rec.has_flag("flag_exports"))
        self.assertFalse(rec.has_flag("flag_free_trade_zone"))
        self.assertFalse(rec.has_flag("not_a_real_flag"))

    def test_flag_bit_order_is_canonical(self):
        expected = (
            "flag_free_trade_zone",
            "flag_deemed_supply",
            "flag_profit_margin",
            "flag_summary_invoice",
            "flag_continuous_supply",
            "flag_disclosed_agent",
            "flag_ecommerce",
            "flag_exports",
        )
        self.assertEqual(UAETransactionType.FLAG_BIT_ORDER, expected)
