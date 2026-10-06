# SPDX-License-Identifier: OPL-1
"""PROP-D1 (P1 release blocker) — property occupancy / double-booking integrity.

Business rule: RULE B (non-overlapping occupancy date ranges), approved by the
product owner 2026-09-04. A property may carry multiple current/future active
contracts as long as their occupancy date ranges do not overlap; only a real
date-range overlap between two 'active' contracts on the same property_id is
rejected. This SUPERSEDES an earlier Rule A implementation (at most one active
contract per property, regardless of dates), whose test file this replaces.

Agent-created verification tests, not part of the original vendor package
(which ships zero native tests).
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "prop_d1")
class TestPropD1DoubleBooking(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.project = cls.env["property.project"].create({"name": "PROP-D1 Project"})
        cls.today = fields.Date.today()

    def _make_property(self, name="PROP-D1 Unit"):
        return self.env["property.details"].create({"name": name, "project_id": self.project.id})

    def _make_tenant(self, name="PROP-D1 Tenant"):
        return self.env["res.partner"].create({"name": name})

    def _make_contract(self, property_id, tenant_id, start_offset, end_offset, rent=50000.0):
        return self.env["rent.contract"].create({
            "property_id": property_id.id,
            "tenant_id": tenant_id.id,
            "start_date": self.today + timedelta(days=start_offset),
            "end_date": (self.today + timedelta(days=end_offset)) if end_offset is not None else False,
            "rent_amount": rent,
        })

    # 1. Exact-date duplicate booking -- full overlap, rejected under Rule B too
    def test_01_exact_date_duplicate_booking_rejected(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -30, 300)
        c1.action_activate()
        c2 = self._make_contract(prop, self._make_tenant("T2"), -30, 300)
        with self.assertRaises(ValidationError):
            c2.action_activate()

    # 2. Partially overlapping lease dates -- rejected
    def test_02_partially_overlapping_dates_rejected(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -30, 300)
        c1.action_activate()
        c2 = self._make_contract(prop, self._make_tenant("T2"), 100, 500)
        with self.assertRaises(ValidationError):
            c2.action_activate()

    # 3. Fully contained/enclosed date range -- rejected
    def test_03_fully_enclosed_range_rejected(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -30, 300)
        c1.action_activate()
        c2 = self._make_contract(prop, self._make_tenant("T2"), 50, 100)
        with self.assertRaises(ValidationError):
            c2.action_activate()

    # 4. RULE B FLIP: adjacent/back-to-back date ranges are ALLOWED, not
    #    rejected -- this is the exact scenario that distinguishes Rule B
    #    from the superseded Rule A (which blocked ANY second active
    #    contract regardless of dates). end_date is the last occupied day;
    #    a contract starting the day AFTER another ends does not overlap.
    def test_04_adjacent_touching_dates_are_allowed_under_rule_b(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -365, 0)  # occupies through today
        c1.action_activate()
        c2 = self._make_contract(prop, self._make_tenant("T2"), 1, 365)  # starts tomorrow
        c2.action_activate()  # must NOT raise
        self.assertEqual(c2.state, "active")
        self.assertEqual(c1.state, "active")

    # 4b. Negative control for the above: starting ON the same day the first
    #     contract's occupancy still covers (i.e. the true boundary) IS an
    #     overlap and must still be rejected.
    def test_04b_same_day_as_still_covered_end_date_rejected(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -365, 0)  # last occupied day = today
        c1.action_activate()
        c2 = self._make_contract(prop, self._make_tenant("T2"), 0, 365)  # starts today too
        with self.assertRaises(ValidationError):
            c2.action_activate()

    # 5. Existing draft/cancelled/expired leases must NOT block a new activation
    def test_05_non_active_states_do_not_block(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        self._make_contract(prop, tenant, -30, 300)  # left in draft, never activated
        cancelled = self._make_contract(prop, self._make_tenant("T2"), -60, 200)
        cancelled.action_activate()
        cancelled.action_cancel()
        expired = self._make_contract(prop, self._make_tenant("T3"), -400, -10)
        expired.action_activate()
        expired.action_expire()
        fresh = self._make_contract(prop, self._make_tenant("T4"), 0, 365)
        fresh.action_activate()  # must NOT raise
        self.assertEqual(fresh.state, "active")

    # 6. Same tenant vs. different tenants -- overlap is blocked either way
    #    (property-level date overlap, not tenant identity)
    def test_06_blocks_regardless_of_same_or_different_tenant(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -30, 300)
        c1.action_activate()
        c2_same_tenant = self._make_contract(prop, tenant, 100, 500)  # overlaps
        with self.assertRaises(ValidationError):
            c2_same_tenant.action_activate()

    # 7. Primary path (action_activate) enforcement
    def test_07_primary_path_action_activate_enforced(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -30, 300)
        c1.action_activate()
        self.assertEqual(prop.state, "rented")
        c2 = self._make_contract(prop, self._make_tenant("T2"), 0, 100)
        with self.assertRaises(ValidationError):
            c2.action_activate()

    # 8. Bypass attempt: direct write({'state': 'active'}) instead of the business method
    def test_08_direct_write_bypass_also_rejected(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -30, 300)
        c1.write({"state": "active"})
        c2 = self._make_contract(prop, self._make_tenant("T2"), 0, 100)
        with self.assertRaises(ValidationError):
            c2.write({"state": "active"})

    # 9. DB-level (not just Python/ORM-level) enforcement -- the exclusion
    #    constraint must be a real PostgreSQL constraint, not only application
    #    code. Verified by going around the ORM entirely with raw SQL.
    def test_09_enforcement_is_a_real_db_constraint_not_only_orm_python(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -30, 300)
        c1.action_activate()
        c2 = self._make_contract(prop, self._make_tenant("T2"), 0, 100)  # overlaps
        from psycopg2.errors import ExclusionViolation
        with self.assertRaises(ExclusionViolation):
            with self.env.cr.savepoint():
                self.env.cr.execute(
                    "UPDATE rent_contract SET state = 'active' WHERE id = %s", (c2.id,)
                )

    # 10. Expiring one contract must not release a property still occupied
    #     TODAY by another active (non-overlapping-with-the-expired-one)
    #     contract. Simulates legacy/pre-fix inconsistent data by temporarily
    #     dropping the exclusion constraint to force the scenario.
    def test_10_expiry_does_not_release_property_occupied_by_another_contract(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c1 = self._make_contract(prop, tenant, -400, 0)  # occupies through today, about to expire
        c1.action_activate()
        c2 = self._make_contract(prop, self._make_tenant("T2"), 0, 365)  # also covers today (legacy bad data)
        with self.env.cr.savepoint():
            self.env.cr.execute("ALTER TABLE rent_contract DROP CONSTRAINT IF EXISTS rent_contract_no_overlap")
            self.env.cr.execute(
                "UPDATE rent_contract SET state = 'active' WHERE id = %s", (c2.id,)
            )
        c2.invalidate_recordset()
        self.assertEqual(c2.state, "active")
        c1.action_expire()
        prop.invalidate_recordset()
        self.assertNotEqual(
            prop.state, "available",
            "expiring one contract released the property while another contract "
            "on it is still active and covers today -- this would let a new "
            "lease be booked over an occupied unit",
        )

    # 11. PROP-D2 (Option A, resolved 2026-09-04): end_date is required=True
    #     at the model level -- this module does not support genuinely
    #     open-ended contracts at all. Negative case: omitting end_date must
    #     be rejected with a FRIENDLY ValidationError (not a raw
    #     NotNullViolation), across the create() chokepoint every entry
    #     vector (UI, RPC, import, batch, cron) shares.
    def test_11_open_ended_contract_rejected_with_friendly_error(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        with self.assertRaises(ValidationError):
            with self.env.cr.savepoint():
                self.env["rent.contract"].create({
                    "property_id": prop.id, "tenant_id": tenant.id,
                    "start_date": self.today, "rent_amount": 50000.0,
                    # end_date deliberately omitted
                })

    # 11b. Positive control: a normal fixed-term contract (end_date supplied)
    #      is unaffected by the Option A validation.
    def test_11b_fixed_term_contract_with_end_date_succeeds(self):
        prop = self._make_property()
        tenant = self._make_tenant()
        c = self._make_contract(prop, tenant, 0, 365)
        self.assertTrue(c.id)
        self.assertTrue(c.end_date)

    # 12. Different property -- never blocks, regardless of identical dates
    def test_12_different_property_never_blocks(self):
        prop1 = self._make_property("PROP-D1 Unit A")
        prop2 = self._make_property("PROP-D1 Unit B")
        tenant = self._make_tenant()
        c1 = self._make_contract(prop1, tenant, -30, 300)
        c1.action_activate()
        c2 = self._make_contract(prop2, self._make_tenant("T2"), -30, 300)
        c2.action_activate()  # must NOT raise
        self.assertEqual(c2.state, "active")
