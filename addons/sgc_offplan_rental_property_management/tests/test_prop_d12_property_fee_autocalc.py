# SPDX-License-Identifier: OPL-1
"""PROP-D12 (P2 usability/data-integrity) -- property.details' Pricing &
Fees tab (registration_fee, admin_fee, total_customer_obligation) sat next to
registration_fee_percentage/admin_fee_percentage with no compute or onchange wired
up at all -- an operator had to manually calculate and type each amount,
with no auto-suggestion from price or the percentage fields, and no
enforcement that registration_fee actually matched price * registration_fee_percentage.
Reported live by a user testing the property form.

Confirmed decision (asked and answered): auto-suggest via @api.onchange,
fields stay plain and manually overridable (not compute=/readonly) --
tenant B already has live properties with real, manually-entered values
in these fields, and forcing a hard compute would silently overwrite them
on the next module upgrade.

Booking amount (booking_wizard.book_price) gets the same auto-suggest
treatment from property.details.booking_percentage, covered separately
below since it lives on a different model (the wizard).

Agent-created verification tests, added alongside the PROP-D12 fix. Uses
odoo.tests.common.Form to genuinely simulate the web client's onchange
execution, not a direct method call -- this is the actual mechanism the
reported symptom (fields not updating live in the form) runs through.
"""
from odoo.tests import Form
from odoo.tests.common import TransactionCase, tagged



@tagged("post_install", "-at_install", "prop_d12")
class TestPropD12PropertyFeeAutocalc(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["property.project"].create({
            "name": "PROP-D12 Project", "company_id": cls.env.company.id,
        })

    # 1. Setting price with the default percentages (Registration Fee 4%, Admin 2%)
    #    must auto-fill registration_fee/admin_fee/total_customer_obligation live,
    #    via the web client's own onchange mechanism (Form helper).
    def test_price_entry_autocalculates_fees_via_form_onchange(self):
        with Form(self.env["property.details"]) as f:
            f.name = "PROP-D12 Property A"
            f.project_id = self.project
            f.price = 1000000.0
            self.assertAlmostEqual(f.registration_fee, 40000.0, places=2)
            self.assertAlmostEqual(f.admin_fee, 20000.0, places=2)
            self.assertAlmostEqual(f.total_customer_obligation, 1060000.0, places=2)

    # 2. Changing the percentage fields (not just price) must also
    #    recalculate -- proves the onchange is keyed on both, not just
    #    price.
    def test_changing_percentage_recalculates_fees(self):
        with Form(self.env["property.details"]) as f:
            f.name = "PROP-D12 Property B"
            f.project_id = self.project
            f.price = 500000.0
            f.registration_fee_percentage = 5.0
            f.admin_fee_percentage = 1.0
            self.assertAlmostEqual(f.registration_fee, 25000.0, places=2)
            self.assertAlmostEqual(f.admin_fee, 5000.0, places=2)
            self.assertAlmostEqual(f.total_customer_obligation, 530000.0, places=2)

    # 3. Maintenance and extra-service costs must fold into the rollup
    #    total only when their own toggle is on -- proves the total isn't
    #    just price+registration_fee+admin unconditionally.
    def test_total_customer_obligation_includes_toggled_extras(self):
        with Form(self.env["property.details"]) as f:
            f.name = "PROP-D12 Property C"
            f.project_id = self.project
            f.price = 200000.0  # registration 8000, admin 4000 at defaults
            f.is_maintenance_service = True
            f.total_maintenance = 3000.0
            f.is_extra_service = True
            f.extra_service_cost = 2000.0
            self.assertAlmostEqual(f.total_customer_obligation, 217000.0, places=2)
            f.is_extra_service = False
            self.assertAlmostEqual(
                f.total_customer_obligation, 215000.0, places=2,
                msg="Turning off Extra Service must drop its cost from the rollup.",
            )

    # 4. The fields remain plain and manually overridable -- an operator
    #    can still type a different registration_fee for a genuinely non-standard
    #    property, and it is NOT silently reverted by the onchange unless
    #    a dependency field (price/percentage/etc.) is touched again.
    def test_fee_fields_remain_manually_overridable(self):
        with Form(self.env["property.details"]) as f:
            f.name = "PROP-D12 Property D"
            f.project_id = self.project
            f.price = 100000.0
            f.registration_fee = 9999.0  # manual override, does not match 4% of price
            self.assertEqual(
                f.registration_fee, 9999.0,
                "A manual edit to registration_fee itself must not be reverted "
                "without a dependency field also changing.",
            )

    # 5. Booking amount (on the Booking Wizard) auto-suggests from the
    #    property's own percentage-based booking rate. default_get() is
    #    called explicitly here (matching this suite's established
    #    pattern for testing default_get-driven fields, e.g. PROP-D8) --
    #    a plain create() would not otherwise invoke it, since book_price
    #    has no field-level `default=`, only this custom default_get()
    #    override, which the web client calls when opening the wizard.
    def test_booking_wizard_book_price_autosuggested_from_property_rate(self):
        prop = self.env["property.details"].create({
            "name": "PROP-D12 Property E", "project_id": self.project.id,
            "price": 400000.0, "booking_type": "percentage",
            "booking_percentage": 10.0,
        })
        Wizard = self.env["booking.wizard"].with_context(active_id=prop.id)
        defaults = Wizard.default_get(
            ["property_id", "ask_price", "book_price",
             "booking_item_id", "broker_item_id"])
        self.assertAlmostEqual(defaults.get("book_price"), 40000.0, places=2)

    # 6. When booking_type is 'fixed' (no percentage basis to compute
    #    from), the wizard must NOT invent a value -- book_price is left
    #    unset by default_get(), for manual entry, since no fixed-amount
    #    source field exists on the property to auto-suggest from.
    def test_booking_wizard_book_price_not_autoset_when_fixed_type(self):
        prop = self.env["property.details"].create({
            "name": "PROP-D12 Property F", "project_id": self.project.id,
            "price": 400000.0, "booking_type": "fixed",
            "booking_percentage": 10.0,
        })
        Wizard = self.env["booking.wizard"].with_context(active_id=prop.id)
        defaults = Wizard.default_get(
            ["property_id", "ask_price", "book_price",
             "booking_item_id", "broker_item_id"])
        self.assertFalse(defaults.get("book_price"))
