# SPDX-License-Identifier: OPL-1
"""PROP-D8 (P2 usability/data-integrity) -- property.vendor's "Create
Booking / Hold" blank form (property.details.action_create_booking)
opens a new record directly on property.vendor with no res_id. Before
this fix, the name field (Vendor Reference) was required=True with no
default, so the web client's own client-side required-field validation
blocked Save before create()'s sequence-assignment override ever ran --
forcing the operator to type a reference manually, defeating the
auto-numbering added in 8afa6f7.

Business rule, confirmed 2026-09-05: name must default to _('New') so
the blank form passes client-side validation, matching this codebase's
own established pattern for every other sequence-generated reference
field (rent_bill.rent_no, rera_form_a's reference field). create()
(unchanged since 8afa6f7) then replaces the 'New' placeholder with the
real ir.sequence value on save. A related lifecycle gap found while
verifying this fix: name had no copy=False, so duplicating a booking
via the standard Odoo "Duplicate" action silently carried the exact
same reference onto the new record -- also fixed here, matching the
established copy=False precedent on every other sequence field in this
module.

Agent-created verification tests, added alongside the PROP-D8 fix
(commit 669b70c + this pass) as its regression test.
"""
from odoo import _
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "prop_d8")
class TestPropD8BookingReferenceDefault(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.vendor_partner = cls.env["res.partner"].create({
            "name": "PROP-D8 Test Vendor",
        })

    # 1. default_get() is what the web client uses to pre-populate a blank
    #    "Create Booking / Hold" form. It must return a non-empty value so
    #    client-side required-field validation does not block Save.
    def test_default_get_name_returns_new_placeholder(self):
        defaults = self.env["property.vendor"].default_get(["name"])
        self.assertEqual(
            defaults.get("name"), _("New"),
            "A blank property.vendor form must default name to 'New' so "
            "the required-field check passes before create() assigns the "
            "real sequence value.",
        )

    # 2. The actual blank-form path: default_get() feeds vals, the form is
    #    saved with 'New' still in vals (nothing typed by the operator),
    #    and create() must replace it with a real PS/... sequence value.
    def test_blank_form_flow_generates_sequence_reference(self):
        vals = self.env["property.vendor"].default_get(["name"])
        vals["vendor_id"] = self.vendor_partner.id
        rec = self.env["property.vendor"].create(vals)
        self.assertNotEqual(
            rec.name, _("New"),
            "A booking saved straight from the blank form must not be "
            "left named 'New' -- create() must assign the real sequence "
            "value.",
        )
        self.assertRegex(
            rec.name, r"^PS/\d{4}/\d{2}/\d{5}$",
            "Generated Vendor Reference must match the registered "
            "ir.sequence pattern (PS/<year>/<month>/<padded number>).",
        )

    # 3. Direct create() with no name key at all (e.g. a server-side/RPC
    #    caller that never went through the web client's default_get) must
    #    still generate a reference -- unchanged behavior since 8afa6f7,
    #    covered here so PROP-D8's fix is proven not to have regressed it.
    def test_direct_create_without_name_also_generates_reference(self):
        rec = self.env["property.vendor"].create({
            "vendor_id": self.vendor_partner.id,
        })
        self.assertNotEqual(rec.name, _("New"))
        self.assertTrue(rec.name)

    # 4. Two bookings created back-to-back must get distinct, sequential
    #    references -- proves the fix does not somehow freeze on the
    #    placeholder or collide.
    def test_two_bookings_get_unique_sequential_references(self):
        rec1 = self.env["property.vendor"].create({
            "vendor_id": self.vendor_partner.id,
        })
        rec2 = self.env["property.vendor"].create({
            "vendor_id": self.vendor_partner.id,
        })
        self.assertNotEqual(
            rec1.name, rec2.name,
            "Sequential bookings must not share the same Vendor Reference.",
        )

    # 5. Duplicating a booking (Odoo's standard "Duplicate" action, i.e.
    #    copy()) must NOT carry over the original's reference number --
    #    found while verifying PROP-D8's full reference lifecycle, fixed
    #    by adding copy=False to match this module's own established
    #    precedent (rent_bill.rent_no, rera_form_a's reference field).
    def test_copy_does_not_duplicate_reference(self):
        original = self.env["property.vendor"].create({
            "vendor_id": self.vendor_partner.id,
        })
        duplicate = original.copy()
        self.assertNotEqual(
            original.name, duplicate.name,
            "Duplicating a booking must not silently produce two live "
            "records sharing the same Vendor Reference.",
        )
        self.assertNotEqual(
            duplicate.name, _("New"),
            "A duplicated booking must get its own real sequence value, "
            "not be left on the 'New' placeholder either.",
        )
