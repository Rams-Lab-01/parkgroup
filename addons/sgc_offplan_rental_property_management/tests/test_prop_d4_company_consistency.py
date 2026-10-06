# SPDX-License-Identifier: OPL-1
"""PROP-D4 (P2 data-integrity) -- rent.contract company must match its
property's company.

Business rule, approved by the product owner 2026-09-04: "A rental
contract's company must equal its property's company. A user must not be
able to activate, import, copy, or modify a contract with a
company/property mismatch." No shared/company-neutral property behavior has
been separately approved, so the rule is a plain equality check with no
special-casing for a False company_id on either side.

Agent-created verification tests, not part of the original vendor package.
Written BEFORE the fix (per the governing instruction) -- run once against
the unfixed source to confirm they fail for the right reason, then again
after the fix to confirm they pass.
"""
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged

from odoo.addons.sgc_offplan_rental_property_management.services.sgc_audit_internal_service import (
    SgcAuditInternalService,
)


@tagged("post_install", "-at_install", "prop_d4")
class TestPropD4CompanyConsistency(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "PROP-D4 Company B"})
        cls.project = cls.env["property.project"].create({
            "name": "PROP-D4 Project", "company_id": cls.company_a.id,
        })
        cls.property_a = cls.env["property.details"].create({
            "name": "PROP-D4 Property A", "project_id": cls.project.id,
            "company_id": cls.company_a.id,
        })
        cls.tenant = cls.env["res.partner"].create({"name": "PROP-D4 Tenant"})

    def _vals(self, **overrides):
        vals = {
            "property_id": self.property_a.id,
            "tenant_id": self.tenant.id,
            "start_date": self.today,
            "end_date": self.today + timedelta(days=100),
            "rent_amount": 50000.0,
        }
        vals.update(overrides)
        return vals

    # 1. Mismatched company during creation.
    def test_01_mismatch_on_create_rejected(self):
        with self.assertRaises(UserError):
            self.env["rent.contract"].create(
                self._vals(company_id=self.company_b.id))

    # 2. Mismatched company during write.
    def test_02_mismatch_on_write_rejected(self):
        c = self.env["rent.contract"].create(self._vals())
        with self.assertRaises(UserError):
            c.write({"company_id": self.company_b.id})

    # 3. Mismatch introduced by property change (contract's company stays A,
    # property changed to one owned by company B).
    def test_03_mismatch_via_property_change_rejected(self):
        property_b = self.env["property.details"].create({
            "name": "PROP-D4 Property B",
            "project_id": self.env["property.project"].create(
                {"name": "PROP-D4 Project B", "company_id": self.company_b.id}).id,
            "company_id": self.company_b.id,
        })
        c = self.env["rent.contract"].create(self._vals())
        with self.assertRaises(UserError):
            c.write({"property_id": property_b.id})

    # 4. Mismatch introduced by contract-company change (inverse of #3).
    def test_04_mismatch_via_contract_company_change_rejected(self):
        c = self.env["rent.contract"].create(self._vals())
        with self.assertRaises(UserError):
            c.write({"company_id": self.company_b.id})

    # 5. Activation of a mismatched draft (mismatch created via a path that
    # bypasses the normal create-time default, then activated).
    def test_05_activation_of_mismatched_draft_rejected(self):
        c = self.env["rent.contract"].create(self._vals())
        # Force a mismatch directly at the DB layer to simulate a draft that
        # became inconsistent through some other means, then attempt to
        # activate it through the normal business method.
        self.env.cr.execute(
            "UPDATE rent_contract SET company_id = %s WHERE id = %s",
            (self.company_b.id, c.id),
        )
        c.invalidate_recordset()
        with self.assertRaises(UserError):
            c.action_activate()

    # 6. Copying a contract into another company.
    def test_06_copy_into_another_company_rejected(self):
        c = self.env["rent.contract"].create(self._vals())
        with self.assertRaises(UserError):
            c.copy(default={"company_id": self.company_b.id})

    # 7. Import / RPC-shaped operation -- same create() entry point external
    # callers use; a dict-based multi-field create is the closest faithful
    # simulation available inside a TransactionCase.
    def test_07_import_rpc_shaped_create_rejected(self):
        with self.assertRaises(UserError):
            self.env["rent.contract"].with_context(import_file=True).create(
                self._vals(company_id=self.company_b.id))

    # 8. Batch write (multiple records, one mismatched).
    def test_08_batch_write_rejected(self):
        c1 = self.env["rent.contract"].create(self._vals())
        c2 = self.env["rent.contract"].create(self._vals(
            start_date=self.today + timedelta(days=200),
            end_date=self.today + timedelta(days=300),
        ))
        batch = c1 + c2
        with self.assertRaises(UserError):
            batch.write({"company_id": self.company_b.id})

    # 9. Valid same-company contract -- must NOT be rejected.
    def test_09_same_company_contract_allowed(self):
        c = self.env["rent.contract"].create(self._vals())
        self.assertEqual(c.company_id, self.property_a.company_id)
        c.action_activate()
        self.assertEqual(c.state, "active")

    # 10. "Shared property" behavior -- not separately approved, so this
    # verifies the plain-equality rule with no special-casing: a property
    # with company_id=False only accepts a contract whose company_id is
    # ALSO False (still equal, not a blanket "anything goes" exception).
    def test_10_no_company_property_requires_matching_no_company_contract(self):
        shared_property = self.env["property.details"].create({
            "name": "PROP-D4 No-Company Property",
            "project_id": self.project.id,
            "company_id": False,
        })
        with self.assertRaises(UserError):
            self.env["rent.contract"].create({
                "property_id": shared_property.id,
                "tenant_id": self.tenant.id,
                "start_date": self.today,
                "end_date": self.today + timedelta(days=100),
                "rent_amount": 50000.0,
                "company_id": self.company_a.id,
            })
        # Matching False == False is allowed (no mismatch).
        c = self.env["rent.contract"].create({
            "property_id": shared_property.id,
            "tenant_id": self.tenant.id,
            "start_date": self.today,
            "end_date": self.today + timedelta(days=100),
            "rent_amount": 50000.0,
            "company_id": False,
        })
        self.assertFalse(c.company_id)

    # 11. Multi-company authorized user -- a user with access to BOTH
    # companies must still be blocked by the data-integrity rule itself
    # (this is a data constraint, not an access-rights gate).
    def test_11_multi_company_authorized_user_still_blocked(self):
        # Protected group grant: the Channel-1 guard owns the path (Tier-1).
        service = SgcAuditInternalService(self.env)
        service.guard_begin("res.users", None)
        multi_user = self.env["res.users"].create({
            "name": "PROP-D4 Multi-Company User",
            "login": "propd4_multi_user",
            "company_id": self.company_a.id,
            "company_ids": [(6, 0, [self.company_a.id, self.company_b.id])],
            "group_ids": [(6, 0, self.env.ref(
                "sgc_offplan_rental_property_management.property_rental_manager").ids)],
        })
        service.guard_end("res.users", None)
        with self.assertRaises(UserError):
            self.env["rent.contract"].with_user(multi_user).create(
                self._vals(company_id=self.company_b.id))

    # 12. Unauthorized cross-company user -- a user without access to
    # company B should be blocked by Odoo's own multi-company access
    # control before/independently of our data constraint.
    def test_12_unauthorized_cross_company_user_blocked(self):
        # Protected group grant: the Channel-1 guard owns the path (Tier-1).
        service = SgcAuditInternalService(self.env)
        service.guard_begin("res.users", None)
        single_user = self.env["res.users"].create({
            "name": "PROP-D4 Single-Company User",
            "login": "propd4_single_user",
            "company_id": self.company_a.id,
            "company_ids": [(6, 0, [self.company_a.id])],
            "group_ids": [(6, 0, self.env.ref(
                "sgc_offplan_rental_property_management.property_rental_manager").ids)],
        })
        service.guard_end("res.users", None)
        with self.assertRaises(Exception):
            self.env["rent.contract"].with_user(single_user).create(
                self._vals(company_id=self.company_b.id))
