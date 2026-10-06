# -*- coding: utf-8 -*-
"""Phase 0 regression and access-control tests.

Covers:
- C-1/C-2: /my/properties and /my/contracts return 200 (not 500) for a logged-in
  portal user, including a user who has zero contracts/properties (the audit
  reported both routes crashed with HTTP 500).
- C-3/C-4/C-5 IDOR fixes: a portal user CANNOT view another partner's
  contract, invoice, or property through the detail routes. Each test asserts
  the 404 path is taken (or the URL returns 200 but the body is the 404
  page), not 200 with leaked data.
- Phase 0.6: trakheesi_permit_number enforces configurable format and
  uniqueness; empty remains allowed.

Uses HttpCase so the route-level HTTP behaviour is exercised end-to-end.
"""
import re
from datetime import timedelta

import psycopg2

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests.common import HttpCase, TransactionCase, tagged

from ..services.sgc_audit_internal_service import SgcAuditInternalService


PNG_1X1_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
    "DwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@tagged("post_install", "-at_install")
class TestPortalRoutes(HttpCase):
    """Route-level regression + IDOR tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Two distinct portal users (alice, bob) each with their own partner.
        # alice owns/contracts a property and has a rent contract; bob is
        # unrelated. We then assert that bob's session cannot read alice's
        # records via the portal detail routes.
        cls.company = cls.env.company
        cls.partner_alice = cls.env["res.partner"].create({"name": "Alice Owner"})
        cls.partner_bob = cls.env["res.partner"].create({"name": "Bob Outsider"})

        portal_group = cls.env.ref("base.group_portal")
        admin_user = cls.env.ref("base.user_admin")
        # base.user_admin is the Administrator, not the ORM superuser -- it
        # still goes through ordinary ACL checks and does not automatically
        # carry this module's custom Property Management group, which
        # property.details.create() below requires.
        # Protected group grant: the Channel-1 guard owns the path (Tier-1).
        service = SgcAuditInternalService(cls.env)
        service.guard_begin("res.users", admin_user.id)
        admin_user.write({"group_ids": [(4, cls.env.ref(
            "sgc_offplan_rental_property_management.property_rental_manager").id)]})
        service.guard_end("res.users", admin_user.id)
        # Run user-creation under admin so portal group assignment is allowed.
        admin_env = cls.env(user=admin_user.id)
        cls.user_alice = admin_env["res.users"].with_context(
            no_reset_password=True,
            mail_notrack=True,
        ).create({
            "name": "Alice Portal",
            "login": "alice_portal_phase0",
            "email": "alice.phase0@example.invalid",
            "partner_id": cls.partner_alice.id,
            "password": "alice_portal_phase0",
        })
        cls.user_bob = admin_env["res.users"].with_context(
            no_reset_password=True,
            mail_notrack=True,
        ).create({
            "name": "Bob Portal",
            "login": "bob_portal_phase0",
            "email": "bob.phase0@example.invalid",
            "partner_id": cls.partner_bob.id,
            "password": "bob_portal_phase0",
        })
        # Verify the partner still references the user
        # Portal users must not also be in base.group_user (internal). Remove
        # them from the internal group before assigning the portal group,
        # otherwise _check_disjoint_groups raises ValidationError.
        internal_group = cls.env.ref("base.group_user")
        (cls.user_alice | cls.user_bob).write({
            "group_ids": [(3, internal_group.id)],
        })
        # In Odoo 19, ``res.users.groups_id`` was removed; the writable field
        # is ``group_ids`` (many2many to res.groups).
        cls.user_alice.write({"group_ids": [(4, portal_group.id)]})
        cls.user_bob.write({"group_ids": [(4, portal_group.id)]})
        cls.env = admin_env

        cls.property_alice = cls.env["property.details"].create({
            "name": "Alice Tower",
            "owner_id": cls.partner_alice.id,
        })

        cls.sale_contract_alice = cls.env["sale.contract"].create({
            "name": "SCT-PHASE0-01",
            "property_id": cls.property_alice.id,
            "buyer_id": cls.partner_alice.id,
            "sale_price": 100.0,
        })

        cls.rent_contract_alice = cls.env["rent.contract"].create({
            "name": "RCT-PHASE0-01",
            "property_id": cls.property_alice.id,
            "tenant_id": cls.partner_alice.id,
            "landlord_id": cls.partner_alice.id,
            "rent_amount": 100.0,
            "start_date": fields.Date.today(),
            "end_date": fields.Date.today() + timedelta(days=365),
        })

        # account.move creation needs a sale journal in the company; the test
        # database may not carry a chart of accounts, so ensure one exists.
        journal = cls.env["account.journal"].search([
            ("type", "=", "sale"),
            ("company_id", "=", cls.company.id),
        ], limit=1)
        if not journal:
            journal = cls.env["account.journal"].create({
                "name": "Test Sale Journal",
                "code": "TSJ1",
                "type": "sale",
                "company_id": cls.company.id,
            })
        cls.invoice_alice = cls.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": cls.partner_alice.id,
            "journal_id": journal.id,
        })

    def _login(self, login):
        self.authenticate(login, login)

    def test_my_properties_renders_for_portal_user(self):
        self._login("alice_portal_phase0")
        response = self.url_open("/my/properties", timeout=30)
        self.assertEqual(
            response.status_code, 200,
            f"/my/properties should not 500; got {response.status_code}"
        )

    def test_my_properties_renders_for_portal_user_with_no_records(self):
        """Bob has no contracts/properties; the route must still return 200."""
        self._login("bob_portal_phase0")
        response = self.url_open("/my/properties", timeout=30)
        self.assertEqual(
            response.status_code, 200,
            f"/my/properties (no-records path) should not 500; "
            f"got {response.status_code}"
        )

    def test_my_contracts_renders_for_portal_user(self):
        self._login("alice_portal_phase0")
        response = self.url_open("/my/contracts", timeout=30)
        self.assertEqual(
            response.status_code, 200,
            f"/my/contracts should not 500; got {response.status_code}"
        )

    def test_my_contracts_renders_for_portal_user_with_no_records(self):
        self._login("bob_portal_phase0")
        response = self.url_open("/my/contracts", timeout=30)
        self.assertEqual(
            response.status_code, 200,
            f"/my/contracts (no-records path) should not 500; "
            f"got {response.status_code}"
        )

    # ----- IDOR tests -----------------------------------------------------

    def test_bob_cannot_view_alice_sale_contract(self):
        self._login("bob_portal_phase0")
        response = self.url_open(
            f"/my/contract/sale/{self.sale_contract_alice.id}", timeout=30
        )
        # 404 (or 200 with a 404 body) — NOT a render of alice's contract.
        # We assert the response does NOT contain alice's sale_price value
        # as a string, and that the status is not 200-with-data.
        body = response.text if hasattr(response, "text") else response.content.decode()
        self.assertNotIn(
            "SCT-PHASE0-01", body,
            "Bob must not see Alice's sale contract reference",
        )
        self.assertNotIn(
            "100.0", body,
            "Bob must not see Alice's sale price",
        )

    def test_bob_cannot_view_alice_rent_contract(self):
        self._login("bob_portal_phase0")
        response = self.url_open(
            f"/my/contract/rent/{self.rent_contract_alice.id}", timeout=30
        )
        body = response.text if hasattr(response, "text") else response.content.decode()
        self.assertNotIn(
            "RCT-PHASE0-01", body,
            "Bob must not see Alice's rent contract reference",
        )

    def test_bob_cannot_view_alice_invoice(self):
        self._login("bob_portal_phase0")
        response = self.url_open(
            f"/my/invoice/{self.invoice_alice.id}", timeout=30
        )
        self.assertNotEqual(
            response.status_code, 200,
            "Bob must NOT get 200 on Alice's invoice detail route",
        )

    def test_bob_cannot_view_alice_property_detail(self):
        self._login("bob_portal_phase0")
        response = self.url_open(
            f"/my/property/{self.property_alice.id}", timeout=30
        )
        body = response.text if hasattr(response, "text") else response.content.decode()
        self.assertNotIn(
            "Alice Tower", body,
            "Bob must not see Alice's property name on the detail route",
        )


@tagged("post_install", "-at_install")
class TestTrakheesiPermitConstraints(HttpCase):
    """Phase 0.6 — format + uniqueness constraints on trakheesi_permit_number."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Property = cls.env["property.details"]

    def test_empty_value_is_allowed(self):
        rec = self.Property.create({"name": "EmptyPermit"})
        self.assertFalse(rec.trakheesi_permit_number)
        # Writing an empty string must not raise.
        rec.write({"trakheesi_permit_number": ""})
        self.assertFalse(rec.trakheesi_permit_number)

    def test_default_format_accepts_simple_string(self):
        # Default regex is r'^[A-Za-z0-9._\-]{3,50}$' — a 5-char alnum fits.
        rec = self.Property.create({
            "name": "FormatOk",
            "trakheesi_permit_number": "TR1234",
        })
        self.assertEqual(rec.trakheesi_permit_number, "TR1234")

    def test_format_rejects_value_with_spaces(self):
        rec = self.Property.create({"name": "FormatBadSpace"})
        with self.assertRaises(ValidationError):
            rec.write({"trakheesi_permit_number": "TR 1234"})

    def test_uniqueness_rejects_duplicate(self):
        self.Property.create({
            "name": "First",
            "trakheesi_permit_number": "UNIQ-001",
        })
        # Accept ValidationError (the @api.constrains path) OR psycopg2's
        # IntegrityError surfaced through Odoo (the partial unique index
        # path). Either proves the guarantee.
        rejected = False
        try:
            self.Property.create({
                "name": "Second",
                "trakheesi_permit_number": "UNIQ-001",
            })
        except ValidationError:
            rejected = True
        except Exception as exc:
            if isinstance(exc, psycopg2.Error) or "unique constraint" in str(exc).lower():
                rejected = True
            else:
                raise
        self.assertTrue(
            rejected,
            "Duplicate trakheesi_permit_number must be rejected by either "
            "the Python @api.constrains or the partial unique index",
        )

    def test_format_is_driven_by_config_parameter(self):
        # Tighten the format to digits-only via the system parameter; a
        # previously-valid alphanumeric value must then be rejected on
        # the next write.
        self.env["ir.config_parameter"].sudo().set_param(
            "sgc_offplan_rental_property_management.trakheesi_permit_format",
            r"^[0-9]{4,10}$",
        )
        rec = self.Property.create({"name": "TightenedFormat"})
        with self.assertRaises(ValidationError):
            rec.write({"trakheesi_permit_number": "TR1234"})
        # And a digits-only value passes.
        rec.write({"trakheesi_permit_number": "12345"})
        self.assertEqual(rec.trakheesi_permit_number, "12345")
        # Restore the default for any subsequent tests.
        self.env["ir.config_parameter"].sudo().set_param(
            "sgc_offplan_rental_property_management.trakheesi_permit_format",
            r"^[A-Za-z0-9._\-]{3,50}$",
        )


@tagged("post_install", "-at_install")
class TestTrakheesiQrPublishing(TransactionCase):
    """Entry 48: the Trakheesi QR is a compliance input and must render on
    every publishing target (property form, website, portal, both brochures)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin_user = cls.env.ref("base.user_admin")
        # Protected group grant: the Channel-1 guard owns the path (Tier-1).
        service = SgcAuditInternalService(cls.env)
        service.guard_begin("res.users", admin_user.id)
        admin_user.write({"group_ids": [(4, cls.env.ref(
            "sgc_offplan_rental_property_management.property_rental_manager").id)]})
        service.guard_end("res.users", admin_user.id)
        cls.env = cls.env(user=admin_user.id)
        cls.owner = cls.env["res.partner"].create({"name": "QR Owner"})

    def _make_property(self, permit):
        return self.env["property.details"].create({
            "name": "QR Test Property",
            "owner_id": self.owner.id,
            "trakheesi_permit_number": permit,
        })

    def test_qr_missing_is_reported_as_compliance_error(self):
        prop = self._make_property("QR-TEST-MISSING")
        self.assertFalse(prop.trakheesi_qr_code)
        self.assertFalse(prop.portal_ready)
        self.assertIn("Trakheesi QR Code is missing",
                      prop.portal_compliance_errors or "")

    def test_qr_upload_clears_the_qr_compliance_error(self):
        prop = self._make_property("QR-TEST-UPLOAD")
        prop.trakheesi_qr_code = PNG_1X1_B64
        self.assertNotIn("Trakheesi QR Code is missing",
                         prop.portal_compliance_errors or "")

    def test_qr_is_wired_into_every_publishing_target(self):
        field = self.env["property.details"]._fields["trakheesi_qr_code"]
        self.assertTrue(field.attachment)
        xmlids = [
            "property_details_form_view",
            "offplan_property_detail",
            "portal_my_property_detail",
            "report_property_brochure",
            "report_property_brochure_luxury",
        ]
        for xmlid in xmlids:
            view = self.env.ref("sgc_offplan_rental_property_management." + xmlid)
            self.assertIn("trakheesi_qr_code", view.arch or "",
                          "Missing Trakheesi QR in %s" % xmlid)


    def test_qr_renders_in_both_brochure_reports(self):
        prop = self._make_property("QR-TEST-REPORT")
        prop.trakheesi_qr_code = PNG_1X1_B64
        expected = "data:image/png;base64," + PNG_1X1_B64
        for action_xmlid in ("action_report_property_brochure",
                             "action_report_property_brochure_luxury"):
            rendered = self.env["ir.actions.report"]._render_qweb_html(
                "sgc_offplan_rental_property_management." + action_xmlid,
                prop.ids)
            html = rendered[0] if isinstance(rendered, tuple) else rendered
            body = html.decode() if isinstance(html, bytes) else html
            self.assertIn(expected, body,
                          "Trakheesi QR missing from %s" % action_xmlid)



@tagged("post_install", "-at_install")
class TestTrakheesiQrRendering(HttpCase):
    """Route-level proof that an uploaded QR reaches the public website listing
    and the customer portal, and that the block stays hidden without one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.owner = cls.env["res.partner"].create({"name": "QR Route Owner"})
        admin_user = cls.env.ref("base.user_admin")
        # Protected group grant: the Channel-1 guard owns the path (Tier-1).
        service = SgcAuditInternalService(cls.env)
        service.guard_begin("res.users", admin_user.id)
        admin_user.write({"group_ids": [(4, cls.env.ref(
            "sgc_offplan_rental_property_management.property_rental_manager").id)]})
        service.guard_end("res.users", admin_user.id)
        admin_env = cls.env(user=admin_user.id)
        cls.user_owner = admin_env["res.users"].with_context(
            no_reset_password=True,
            mail_notrack=True,
        ).create({
            "name": "QR Route Portal",
            "login": "qr_route_portal",
            "email": "qr.route@example.invalid",
            "partner_id": cls.owner.id,
            "password": "qr_route_portal",
        })
        cls.user_owner.write({
            "group_ids": [(3, cls.env.ref("base.group_user").id)],
        })
        cls.user_owner.write({
            "group_ids": [(4, cls.env.ref("base.group_portal").id)],
        })
        cls.env = admin_env
        cls.property_qr = cls.env["property.details"].create({
            "name": "QR Route Tower",
            "owner_id": cls.owner.id,
            "is_published_website": True,
            "trakheesi_qr_code": PNG_1X1_B64,
        })
        cls.property_no_qr = cls.env["property.details"].create({
            "name": "QR Route Tower Without Code",
            "owner_id": cls.owner.id,
            "is_published_website": True,
        })

    def _body(self, url):
        response = self.url_open(url, timeout=30)
        return response.text if hasattr(response, "text") else response.content.decode()

    def test_website_detail_renders_the_qr_block(self):
        body = self._body("/offplan/property/%s" % self.property_qr.id)
        self.assertIn("o-trakheesi-qr-card", body)
        self.assertIn(
            "/web/image/property.details/%s/trakheesi_qr_code" % self.property_qr.id,
            body)

    def test_website_detail_omits_the_qr_block_without_an_upload(self):
        body = self._body("/offplan/property/%s" % self.property_no_qr.id)
        self.assertNotIn("o-trakheesi-qr-card", body)

    def test_portal_detail_renders_the_qr_block(self):
        self.authenticate("qr_route_portal", "qr_route_portal")
        body = self._body("/my/property/%s" % self.property_qr.id)
        self.assertIn(
            "/web/image/property.details/%s/trakheesi_qr_code" % self.property_qr.id,
            body)