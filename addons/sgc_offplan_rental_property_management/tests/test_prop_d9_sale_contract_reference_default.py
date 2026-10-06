# SPDX-License-Identifier: OPL-1
"""PROP-D9 (P2 usability/data-integrity) -- sale.contract's blank direct-
creation forms (property.details.action_create_sale_contract, and
unrestricted "+New" from the Sale Contracts list view) have the same
structural shape that caused PROP-D8 on property.vendor: name was
required=True with no default, so the web client's client-side
required-field validation would block Save before create()'s existing
sequence-assignment ever ran.

Authorized fix, matching the established property.vendor (PROP-D8)
pattern exactly: default=lambda self: _('New'), copy=False. create()
(unchanged) continues to assign the real reference unconditionally at
creation time; _assign_reference() (called from action_sign()/
action_complete()) is confirmed a no-op in the ordinary flow since the
reference is already real by the time either method runs.

Investigation-only findings that authorized this fix are recorded in the
mission ledger's PROP-D8 update (docs/SGC_RENT_PILOT_LOGS/MISSION_LEDGER.md)
and formalized in SGC_RENT_DEFECT_RECORDS_D9_D10.md.

Agent-created verification tests, added alongside the PROP-D9 fix as its
regression test.
"""
from datetime import timedelta

from odoo import _
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "prop_d9")
class TestPropD9SaleContractReferenceDefault(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "PROP-D9 Company B"})
        cls.project = cls.env["property.project"].create({
            "name": "PROP-D9 Project", "company_id": cls.company_a.id,
        })
        cls.property_a = cls.env["property.details"].create({
            "name": "PROP-D9 Property A", "project_id": cls.project.id,
            "company_id": cls.company_a.id,
        })
        cls.buyer = cls.env["res.partner"].create({"name": "PROP-D9 Buyer"})

    def _vals(self, **overrides):
        vals = {
            "property_id": self.property_a.id,
            "buyer_id": self.buyer.id,
        }
        vals.update(overrides)
        return vals

    # 1. default_get() is what the web client uses to pre-populate a blank
    #    direct-creation form. Must return a non-empty value.
    def test_default_get_name_returns_new_placeholder(self):
        defaults = self.env["sale.contract"].default_get(["name"])
        self.assertEqual(defaults.get("name"), _("New"))

    # 2. The blank-form path: default_get() feeds vals, 'New' is still
    #    present, create() must replace it with a real SC/... value.
    def test_blank_form_flow_generates_sequence_reference(self):
        vals = self.env["sale.contract"].default_get(["name"])
        vals.update(self._vals())
        rec = self.env["sale.contract"].create(vals)
        self.assertNotEqual(rec.name, _("New"))
        self.assertRegex(rec.name, r"^SC/\d{4}/\d{5}$")

    # 3. copy() must not duplicate the source reference, and must not leave
    #    the duplicate on the 'New' placeholder either.
    def test_copy_generates_new_reference_not_duplicate(self):
        original = self.env["sale.contract"].create(self._vals())
        duplicate = original.copy()
        self.assertNotEqual(original.name, duplicate.name)
        self.assertNotEqual(duplicate.name, _("New"))

    # 4. Explicit duplicate reference via direct write() -- disclosed,
    #    known gap: no _sql_constraints uniqueness exists on `name` for
    #    this model (confirmed by reading the model definition), same as
    #    property.vendor before and after PROP-D8. This fix's authorized
    #    scope is the default/copy=False pair only, not a new DB
    #    constraint (which would be a schema change against a model that
    #    may already carry real tenant data, out of scope here and not
    #    authorized). This test documents CURRENT behavior honestly rather
    #    than asserting protection that does not exist.
    def test_explicit_duplicate_reference_not_rejected_known_gap(self):
        rec1 = self.env["sale.contract"].create(self._vals())
        rec2 = self.env["sale.contract"].create(self._vals())
        rec2.write({"name": rec1.name})
        self.assertEqual(
            rec1.name, rec2.name,
            "Documents a known, pre-existing gap: this model has no unique "
            "constraint on name, so an explicit write() can still produce "
            "a duplicate reference. Not part of PROP-D9's authorized fix "
            "scope (default + copy=False only) -- flagged, not silently "
            "left undocumented.",
        )

    # 5. Company-specific sequence behavior: the ir.sequence backing this
    #    model's reference (code='sale.contract') is global
    #    (company_id eval="False" in data/sequence.xml), same as
    #    property.vendor. Confirms no cross-company collision, and that
    #    this is the existing, unchanged design -- not scoped by company.
    def test_company_scoping_is_global_no_cross_company_collision(self):
        property_b = self.env["property.details"].create({
            "name": "PROP-D9 Property B",
            "project_id": self.env["property.project"].create(
                {"name": "PROP-D9 Project B", "company_id": self.company_b.id}).id,
            "company_id": self.company_b.id,
        })
        rec_a = self.env["sale.contract"].create(
            self._vals(company_id=self.company_a.id))
        rec_b = self.env["sale.contract"].create(self._vals(
            property_id=property_b.id, company_id=self.company_b.id))
        self.assertNotEqual(
            rec_a.name, rec_b.name,
            "References must remain unique across companies even though "
            "the backing sequence is global, not company-scoped.",
        )

    # 6. Rapid sequential creation (proxy for concurrent creation within
    #    this test framework's single-connection constraints) must not
    #    duplicate references. True multi-connection locking is handled by
    #    Odoo core's ir.sequence.next_by_code, not re-implemented here.
    def test_sequential_creates_do_not_duplicate_references(self):
        names = [self.env["sale.contract"].create(self._vals()).name
                 for _i in range(5)]
        self.assertEqual(
            len(names), len(set(names)),
            "5 sequential creates must produce 5 distinct references.",
        )

    # 7. action_sign()/action_complete() must not reassign an already-real
    #    reference (confirms _assign_reference() is a no-op in the
    #    ordinary flow, since create() already resolved the real value).
    def test_action_sign_and_complete_do_not_reassign_existing_reference(self):
        rec = self.env["sale.contract"].create(self._vals())
        name_after_create = rec.name
        rec.action_sign()
        self.assertEqual(rec.name, name_after_create)
        rec.action_complete()
        self.assertEqual(rec.name, name_after_create)

    # 8. No record can be left permanently named 'New' -- create() resolves
    #    it unconditionally today, regardless of the default's placeholder.
    def test_no_persisted_contract_remains_named_new(self):
        rec = self.env["sale.contract"].create(self._vals())
        self.assertNotEqual(rec.name, _("New"))
        stray = self.env["sale.contract"].search([("name", "=", _("New"))])
        self.assertFalse(
            stray,
            "No sale.contract record should ever persist with name == 'New'.",
        )

    # 9. Genuine browser Save on the actual blank-form UI path remains
    #    pending -- not testable here (no browser automation in this
    #    module's test suite, and no tenant login credential is held by
    #    the session that authored this fix). Documented, not concealed --
    #    see SGC_RENT_DEFECT_RECORDS_D9_D10.md.
