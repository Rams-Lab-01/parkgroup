# SPDX-License-Identifier: OPL-1
"""PROP-D10 (P2 usability/data-integrity) -- rent.contract's blank direct-
creation forms (property.details.action_create_rent_contract, and
unrestricted "+New" from the Rent Contracts list view) have the same
structural shape that caused PROP-D8 on property.vendor: name was
required=True with no default, so the web client's client-side
required-field validation would block Save before create()'s existing
sequence-assignment ever ran.

Authorized fix, matching the established property.vendor (PROP-D8)
pattern exactly: default=lambda self: _('New'), copy=False. create()
(unchanged) continues to assign the real reference unconditionally at
creation time; _assign_reference() (called from action_activate()) is
confirmed a no-op in the ordinary flow since the reference is already
real by the time it runs.

Investigation-only findings that authorized this fix are recorded in the
mission ledger's PROP-D8 update (docs/SGC_RENT_PILOT_LOGS/MISSION_LEDGER.md)
and formalized in SGC_RENT_DEFECT_RECORDS_D9_D10.md.

Agent-created verification tests, added alongside the PROP-D10 fix as its
regression test. All records here are created/left in 'draft' state unless
a test specifically exercises action_activate() -- the model's own Rule B
exclusion constraint only applies to state='active', so draft-state
fixtures never collide regardless of date overlap.
"""
from datetime import timedelta

from odoo import _, fields
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install", "prop_d10")
class TestPropD10RentContractReferenceDefault(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.today = fields.Date.today()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "PROP-D10 Company B"})
        cls.project = cls.env["property.project"].create({
            "name": "PROP-D10 Project", "company_id": cls.company_a.id,
        })
        cls.property_a = cls.env["property.details"].create({
            "name": "PROP-D10 Property A", "project_id": cls.project.id,
            "company_id": cls.company_a.id,
        })
        cls.tenant = cls.env["res.partner"].create({"name": "PROP-D10 Tenant"})

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

    # 1. default_get() is what the web client uses to pre-populate a blank
    #    direct-creation form. Must return a non-empty value.
    def test_default_get_name_returns_new_placeholder(self):
        defaults = self.env["rent.contract"].default_get(["name"])
        self.assertEqual(defaults.get("name"), _("New"))

    # 2. The blank-form path: default_get() feeds vals, 'New' is still
    #    present, create() must replace it with a real RC/... value.
    def test_blank_form_flow_generates_sequence_reference(self):
        vals = self.env["rent.contract"].default_get(["name"])
        vals.update(self._vals())
        rec = self.env["rent.contract"].create(vals)
        self.assertNotEqual(rec.name, _("New"))
        self.assertRegex(rec.name, r"^RC/\d{4}/\d{5}$")

    # 3. copy() must not duplicate the source reference, and must not leave
    #    the duplicate on the 'New' placeholder either. copy() of an
    #    active-shaped draft is fine here since the duplicate stays draft
    #    (copy() does not carry over an 'active' state re-trigger).
    def test_copy_generates_new_reference_not_duplicate(self):
        original = self.env["rent.contract"].create(self._vals())
        duplicate = original.copy()
        self.assertNotEqual(original.name, duplicate.name)
        self.assertNotEqual(duplicate.name, _("New"))

    # 4. Explicit duplicate reference via direct write() -- disclosed,
    #    known gap: no _sql_constraints uniqueness exists on `name` for
    #    this model (confirmed by reading the model definition), same as
    #    property.vendor and sale.contract. Not part of PROP-D10's
    #    authorized fix scope (default + copy=False only).
    def test_explicit_duplicate_reference_not_rejected_known_gap(self):
        rec1 = self.env["rent.contract"].create(self._vals())
        rec2 = self.env["rent.contract"].create(self._vals(
            start_date=self.today + timedelta(days=200),
            end_date=self.today + timedelta(days=300),
        ))
        rec2.write({"name": rec1.name})
        self.assertEqual(
            rec1.name, rec2.name,
            "Documents a known, pre-existing gap: this model has no unique "
            "constraint on name. Not part of PROP-D10's authorized fix "
            "scope -- flagged, not silently left undocumented.",
        )

    # 5. Company-specific sequence behavior: the ir.sequence backing this
    #    model's reference (code='rent.contract') is global
    #    (company_id eval="False" in data/sequence.xml). Confirms no
    #    cross-company collision.
    def test_company_scoping_is_global_no_cross_company_collision(self):
        property_b = self.env["property.details"].create({
            "name": "PROP-D10 Property B",
            "project_id": self.env["property.project"].create(
                {"name": "PROP-D10 Project B", "company_id": self.company_b.id}).id,
            "company_id": self.company_b.id,
        })
        tenant_b = self.env["res.partner"].create({"name": "PROP-D10 Tenant B"})
        rec_a = self.env["rent.contract"].create(
            self._vals(company_id=self.company_a.id))
        rec_b = self.env["rent.contract"].create(self._vals(
            property_id=property_b.id, tenant_id=tenant_b.id,
            company_id=self.company_b.id))
        self.assertNotEqual(rec_a.name, rec_b.name)

    # 6. Rapid sequential creation (draft state, no overlap-constraint
    #    interaction) must not duplicate references.
    def test_sequential_creates_do_not_duplicate_references(self):
        names = [
            self.env["rent.contract"].create(self._vals(
                start_date=self.today + timedelta(days=i * 10),
                end_date=self.today + timedelta(days=i * 10 + 5),
            )).name
            for i in range(5)
        ]
        self.assertEqual(len(names), len(set(names)))

    # 7. action_activate() (this model's equivalent of
    #    action_sign()/action_complete()) must not reassign an
    #    already-real reference.
    def test_action_activate_does_not_reassign_existing_reference(self):
        rec = self.env["rent.contract"].create(self._vals())
        name_after_create = rec.name
        rec.action_activate()
        self.assertEqual(rec.name, name_after_create)

    # 8. No record can be left permanently named 'New'.
    def test_no_persisted_contract_remains_named_new(self):
        rec = self.env["rent.contract"].create(self._vals())
        self.assertNotEqual(rec.name, _("New"))
        stray = self.env["rent.contract"].search([("name", "=", _("New"))])
        self.assertFalse(stray)

    # 9. Genuine browser Save on the actual blank-form UI path remains
    #    pending -- not testable here (no browser automation in this
    #    module's test suite, and no tenant login credential is held by
    #    the session that authored this fix). Documented, not concealed --
    #    see SGC_RENT_DEFECT_RECORDS_D9_D10.md.
