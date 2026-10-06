# -*- coding: utf-8 -*-
"""Entry 50: the Tier-1 delete gate's UI workflow.

Covers the delete-with-reason path at the model/UI-contract level:

- the standard delete is still refused without a registered reason;
- the wizard's Delete button registers the sanitized reason and performs the
  governed unlink in one transaction, producing ONE Tier-1 event per record
  with the reason persisted and a per-field snapshot read while the row existed;
- multi-record deletes (list selection via active_ids, explicit res_ids) write
  one event per record;
- a too-short reason fails closed and deletes nothing;
- a model outside the mixin is refused;
- every gated model (mixin + _audit_unlink_requires_reason = True) has exactly
  one bound "Delete with audit reason" action, and exempt models have none.
"""
from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase, tagged

from ..services.sgc_audit_internal_service import SgcAuditInternalService

REASON = "Entry 50 test - deleting a superseded duration row"


@tagged("post_install", "-at_install")
class TestAuditDeleteWorkflow(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        admin_user = cls.env.ref("base.user_admin")
        # Protected group grants: the Channel-1 guard owns the path (Tier-1).
        # The audit viewer group is required so the test can READ the events
        # it produces (the event model is read-restricted to audit groups).
        service = SgcAuditInternalService(cls.env)
        service.guard_begin("res.users", admin_user.id)
        admin_user.write({"group_ids": [
            (4, cls.env.ref(
                "sgc_offplan_rental_property_management.property_rental_manager").id),
            (4, cls.env.ref(
                "sgc_offplan_rental_property_management.sgc_audit_viewer_group").id),
        ]})
        service.guard_end("res.users", admin_user.id)
        cls.env = cls.env(user=admin_user.id)
        cls.Event = cls.env["sgc.critical.audit.event"]
        cls.Wizard = cls.env["sgc.critical.audit.reason.wizard"]

    def _make_duration(self, name):
        return self.env["contract.duration"].create({"name": name, "month": 3})

    def _wizard(self, ids, **vals):
        payload = {
            "model": "contract.duration",
            "res_id": ids[0],
            "operation": "Record deleted",
            "operation_kind": "unlink",
            "reason": REASON,
        }
        payload.update(vals)
        return self.Wizard.with_context(
            active_ids=ids, active_model="contract.duration").create(payload)

    def _unlink_events(self, res_id):
        return self.Event.search([
            ("model", "=", "contract.duration"),
            ("res_id", "=", res_id),
            ("operation", "=", "unlink"),
        ])

    def test_standard_delete_without_reason_is_still_refused(self):
        rec = self._make_duration("Gate Refusal")
        with self.assertRaises(ValidationError):
            rec.unlink()
        self.assertTrue(rec.exists())
        self.assertEqual(self._unlink_events(rec.id), self.Event)

    def test_wizard_delete_registers_reason_and_captures_snapshot(self):
        rec = self._make_duration("Wizard Delete")
        res_id = rec.id
        self._wizard([res_id]).action_confirm_and_unlink()
        self.assertFalse(self.env["contract.duration"].browse(res_id).exists())
        events = self._unlink_events(res_id)
        self.assertEqual(len(events), 1)
        self.assertEqual(events.tier, "1")
        self.assertEqual(events.reason, REASON)
        self.assertEqual(events.source, "unlink")
        name_rows = events.field_changes.filtered(lambda c: c.field_name == "name")
        self.assertEqual(
            len(name_rows), 1,
            "the deleted row must carry a snapshot row for every watched field")
        # contract.duration.name has no explicit redaction policy, so the
        # fail-closed default (P0-10) stores the marker, not the value. The
        # assertion that matters here is that the row WAS read pre-delete (R27).
        self.assertEqual(name_rows.old_value, "[REDACTED-FIELD]")

    def test_wizard_delete_honours_the_list_selection(self):
        recs = self.env["contract.duration"].create([
            {"name": "Bulk A", "month": 1},
            {"name": "Bulk B", "month": 2},
        ])
        ids = recs.ids
        self._wizard(ids).action_confirm_and_unlink()
        for res_id in ids:
            self.assertFalse(self.env["contract.duration"].browse(res_id).exists())
            events = self._unlink_events(res_id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events.reason, REASON)

    def test_wizard_delete_accepts_explicit_res_ids(self):
        rec = self._make_duration("Explicit IDs")
        res_id = rec.id
        wizard = self.Wizard.create({
            "model": "contract.duration",
            "res_id": res_id,
            "res_ids": "%s" % res_id,
            "operation": "Record deleted",
            "operation_kind": "unlink",
            "reason": REASON,
        })
        wizard.action_confirm_and_unlink()
        self.assertFalse(self.env["contract.duration"].browse(res_id).exists())

    def test_short_reason_fails_closed(self):
        rec = self._make_duration("Short Reason")
        wizard = self._wizard([rec.id], reason="no")
        with self.assertRaises(ValidationError):
            wizard.action_confirm_and_unlink()
        self.assertTrue(rec.exists())
        self.assertEqual(self._unlink_events(rec.id), self.Event)

    def test_unwired_model_is_refused(self):
        wizard = self.Wizard.create({
            "model": "res.currency",
            "res_id": 1,
            "operation": "Record deleted",
            "operation_kind": "unlink",
            "reason": REASON,
        })
        with self.assertRaises(UserError):
            wizard.action_confirm_and_unlink()

    def test_every_gated_model_has_exactly_one_bound_delete_action(self):
        Action = self.env["ir.actions.act_window"]
        Model = self.env["ir.model"]
        gated, exempt = [], []
        for name, model in self.env.registry.items():
            if model._name != name or getattr(model, "_abstract", False):
                continue
            inherit = model._inherit
            if isinstance(inherit, str):
                inherit = [inherit]
            if "sgc.critical.audit.mixin" not in (inherit or []):
                continue
            if getattr(model, "_audit_unlink_requires_reason", True):
                gated.append(name)
            else:
                exempt.append(name)
        self.assertTrue(gated, "no gated models found - the registry scan is wrong")
        for name in sorted(gated):
            ir_model = Model.search([("model", "=", name)], limit=1)
            self.assertTrue(ir_model, "ir.model missing for %s" % name)
            found = Action.search_count([
                ("res_model", "=", "sgc.critical.audit.reason.wizard"),
                ("binding_model_id", "=", ir_model.id),
            ])
            self.assertEqual(
                found, 1,
                "expected exactly one delete-with-reason action for %s" % name)
        for name in sorted(exempt):
            ir_model = Model.search([("model", "=", name)], limit=1)
            found = Action.search_count([
                ("res_model", "=", "sgc.critical.audit.reason.wizard"),
                ("binding_model_id", "=", ir_model.id),
            ])
            self.assertEqual(
                found, 0,
                "exempt model %s must not offer the gated delete" % name)


    def test_wizard_default_get_computes_selection_server_side(self):
        """py.js has no `len`, so the selection size cannot ride the action
        context; the wizard must compute it from active_ids server-side."""
        recs = self.env["contract.duration"].create([
            {"name": "Defaults A", "month": 1},
            {"name": "Defaults B", "month": 2},
        ])
        wizard = self.Wizard.with_context(
            active_model="contract.duration",
            active_ids=recs.ids,
            active_id=recs.ids[0],
        ).create({
            "model": "contract.duration",
            "res_id": recs.ids[0],
            "operation": "Record deleted",
            "operation_kind": "unlink",
            "reason": REASON,
        })
        self.assertEqual(wizard.target_count, 2)
        self.assertEqual(wizard.res_ids,
                         ",".join(str(rid) for rid in recs.ids))

    def test_wizard_default_get_single_selection(self):
        rec = self._make_duration("Defaults Single")
        wizard = self.Wizard.with_context(
            active_model="contract.duration",
            active_ids=[rec.id],
            active_id=rec.id,
        ).create({
            "model": "contract.duration",
            "res_id": rec.id,
            "operation": "Record deleted",
            "operation_kind": "unlink",
            "reason": REASON,
        })
        self.assertEqual(wizard.target_count, 1)
        self.assertFalse(wizard.res_ids)

    def test_bound_delete_action_contexts_are_client_safe(self):
        """py.js evaluates action contexts and does not expose `len`; the
        bound actions must stay literal-only (Entry 52 live defect)."""
        actions = self.env["ir.actions.act_window"].search([
            ("res_model", "=", "sgc.critical.audit.reason.wizard"),
            ("binding_model_id", "!=", False),
        ])
        self.assertTrue(actions)
        for action in actions:
            context = action.context or ""
            self.assertNotIn(
                "len(", context,
                "action %s (%s) carries len() in its context; the web client "
                "cannot evaluate it (Name 'len' is not defined)"
                % (action.id, action.name))