# SPDX-License-Identifier: OPL-1
"""PROP-D11 (P2 usability/workflow) -- property.vendor's "Cancel" button was
hidden whenever state was 'confirmed' OR 'cancelled'
(invisible="state in ('confirmed', 'cancelled')"), so once a booking was
confirmed there was no UI path to cancel it or ever return it to draft.
Reported live by a user testing the Booking/Hold form.

Confirmed decision (asked and answered): Cancel must be available from
both 'draft' and 'confirmed' (hidden only once already 'cancelled'), and a
new "Set to Draft" action is added, reachable only from 'cancelled' --
not directly from 'confirmed', so un-booking the property (already
handled by action_cancel) always happens before a return to draft.

Agent-created verification tests, added alongside the PROP-D11 fix.
"""
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "prop_d11")
class TestPropD11BookingStateTransitions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["property.project"].create({
            "name": "PROP-D11 Project", "company_id": cls.env.company.id,
        })
        cls.property = cls.env["property.details"].create({
            "name": "PROP-D11 Property", "project_id": cls.project.id,
            "company_id": cls.env.company.id,
        })
        cls.vendor_partner = cls.env["res.partner"].create({
            "name": "PROP-D11 Vendor",
        })

    def _new_booking(self):
        return self.env["property.vendor"].create({
            "vendor_id": self.vendor_partner.id,
            "property_id": self.property.id,
        })

    # 1. A confirmed booking must still be cancellable (the actual reported
    #    defect -- previously blocked at the view layer, but exercising the
    #    model method directly here since it's the ORM-level guarantee the
    #    fix depends on; the button visibility itself is a view-layer fix
    #    with no server-side equivalent to unit test).
    def test_confirmed_booking_can_be_cancelled(self):
        booking = self._new_booking()
        booking.action_confirm()
        self.assertEqual(booking.state, "confirmed")
        self.assertEqual(self.property.state, "booked")
        booking.action_cancel()
        self.assertEqual(booking.state, "cancelled")
        self.assertEqual(
            self.property.state, "available",
            "Cancelling a confirmed booking must release the property.",
        )

    # 2. A draft booking (never confirmed) must also remain cancellable --
    #    proves the fix didn't accidentally narrow Cancel to confirmed-only.
    def test_draft_booking_can_be_cancelled(self):
        booking = self._new_booking()
        self.assertEqual(booking.state, "draft")
        booking.action_cancel()
        self.assertEqual(booking.state, "cancelled")

    # 3. A cancelled booking can be reset to draft.
    def test_cancelled_booking_can_be_reset_to_draft(self):
        booking = self._new_booking()
        booking.action_cancel()
        booking.action_draft()
        self.assertEqual(booking.state, "draft")

    # 4. A confirmed booking cannot skip straight to draft -- must be
    #    cancelled first. Server-side guard, not just a hidden button.
    def test_confirmed_booking_cannot_skip_directly_to_draft(self):
        booking = self._new_booking()
        booking.action_confirm()
        with self.assertRaises(UserError):
            booking.action_draft()
        self.assertEqual(
            booking.state, "confirmed",
            "A rejected action_draft() call must not change state.",
        )

    # 5. A draft booking (never cancelled) also cannot be sent to draft
    #    again via action_draft() -- same guard applies uniformly.
    def test_draft_booking_cannot_call_action_draft(self):
        booking = self._new_booking()
        with self.assertRaises(UserError):
            booking.action_draft()
