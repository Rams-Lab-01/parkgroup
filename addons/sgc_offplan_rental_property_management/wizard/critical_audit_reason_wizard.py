# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

"""Critical-Change Audit — Tier-1 reason wizard (design §5.5, [P0-12]).

Transient wizard that collects the mandatory operator reason for a Tier-1
operation.  On Confirm:

* the reason is sanitized EXACTLY ONCE (§8.8: control-char strip, secret
  masking, length 5-500) via ``SgcAuditInternalService.register_reason``;
* the SAME sanitized value is later written to BOTH the audit event ``reason``
  and the business record's reason field (P0-12) — the wrapper reuses the
  wizard's sanitized string, and re-sanitization is idempotent;
* the sanitized reason travels as a typed parameter through the service's
  per-transaction registry — NEVER via ``env.context`` [C8].

The wizard itself does not execute the business action; it registers the
reason so the Tier-1 wrapper can proceed and ``consume_reason`` after a
successful write (reason is discarded on failure: the transaction rolls back).
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class CriticalAuditReasonWizard(models.TransientModel):
    _name = 'sgc.critical.audit.reason.wizard'
    _description = 'Critical Audit Reason Wizard'

    model = fields.Char(
        string='Model',
        required=True,
        readonly=True,
        help='Technical name of the business model that is about to change.',
    )
    res_id = fields.Integer(
        string='Record ID',
        required=True,
        readonly=True,
    )
    operation = fields.Char(
        string='Operation',
        required=True,
        readonly=True,
        help='Tier-1 operation label shown on the audit event.',
    )
    reason = fields.Text(
        string='Reason',
        required=True,
        help='This action is logged. Do not enter passwords, tokens, '
             'payment details, or unnecessary personal information.',
    )
    correlation_uuid = fields.Char(
        string='Correlation UUID',
        size=36,
        readonly=True,
        copy=False,
    )
    res_ids = fields.Char(
        string='Record IDs',
        readonly=True,
        help='Comma-separated ids when the action targets several records. '
             'Filled from the list selection; empty for a single record.',
    )
    operation_kind = fields.Selection([
        ('register', 'Register the reason only'),
        ('unlink', 'Delete the record(s)'),
    ], string='Action', default='register', required=True, readonly=True,
        help='register: only records the reason for a wrapper that follows in '
             'the same transaction. unlink: this wizard itself deletes the '
             'record(s) under the registered reason (the reason registry lives '
             'in-process and per-transaction, so the delete must happen here).')
    target_count = fields.Integer(
        string='Records', readonly=True,
        help='How many records the delete will cover.',
    )

    @api.model
    def default_get(self, fields_list):
        """Fill the delete targets from the context, server-side.

        Odoo evaluates an action's context CLIENT-side (py.js) before the
        wizard form opens; that evaluator exposes active_id/active_ids but not
        ``len`` (production defect 2026-09-20: "Name 'len' is not defined" on
        every bound delete action).  The bound actions therefore pass literals
        and active_id only, and the selection size / id list is computed here,
        where real Python runs.
        """
        res = super().default_get(fields_list)
        ctx_ids = [rid for rid in (self.env.context.get('active_ids') or [])
                   if rid]
        if not ctx_ids:
            active_id = self.env.context.get('active_id')
            if active_id:
                ctx_ids = [active_id]
        if 'res_ids' in fields_list and len(ctx_ids) > 1:
            res['res_ids'] = ','.join(str(rid) for rid in ctx_ids)
        if 'target_count' in fields_list:
            res['target_count'] = len(ctx_ids) or 1
        return res

    def action_confirm(self):
        """Register the sanitized Tier-1 reason and close the wizard.

        Called from the form's Confirm button.  ``register_reason`` sanitizes
        §8.8, validates the 5-500 length, and stores the CLEAN value (plus a
        fresh correlation uuid) in the per-transaction reason registry.
        The caller's action wrapper then consumes it via ``consume_reason``.
        """
        self.ensure_one()
        if not self.model or not self.res_id or not self.operation:
            raise UserError(_('The audit reason wizard was invoked without a target record.'))
        try:
            entry = self._register()
        except Exception as err:
            # Friendly message for the operator; the underlying failure is in
            # the log so the business op stays blocked (fail-closed, C1).
            raise UserError(
                _('The audit reason could not be recorded: %s') % str(err)
            ) from err
        self.correlation_uuid = entry.get('correlation_uuid')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Reason recorded'),
                'message': _('This action is logged and will be audited.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def action_confirm_and_unlink(self):
        """Register the reason and delete the target record(s) — one transaction.

        The reason registry is in-process and keyed by transaction, so a wizard
        that only registered the reason left it unusable: by the time the
        operator pressed the standard delete, the registration was gone. This
        button therefore performs the governed delete itself:

        1. resolve and validate the targets (governed model, reason required);
        2. register the sanitized reason once per record;
        3. let the mixin's ``unlink`` consume it and capture the Tier-1 event
           with the per-field snapshot, in this same transaction.

        Any failure (ACL, gate, capture, chain) raises and rolls the whole thing
        back — fail-closed, C1 — and the registered reasons die with it.
        """
        self.ensure_one()
        records = self._resolve_target_records()
        for rec in records:
            self._register_for(rec._name, rec.id)
        count = len(records)
        records.unlink()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Deleted'),
                'message': _('%s record(s) deleted and logged with the operator reason.', count),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _resolve_target_records(self):
        """Validate context and return the recordset the delete will cover."""
        if not self.model:
            raise UserError(_('The audit reason wizard was invoked without a target model.'))
        Model = self.env.get(self.model)
        if Model is None:
            raise UserError(_('Unknown model %(model)s.', model=self.model))
        if 'sgc.critical.audit.mixin' not in Model._inherit:
            raise UserError(_(
                '%(model)s is not audit-governed; use the standard delete.',
                model=self.model))
        ids = self._target_ids()
        if not ids:
            raise UserError(_('No records were passed to the delete workflow.'))
        records = Model.browse(ids).exists()
        if not records:
            raise UserError(_('The record(s) no longer exist.'))
        missing = list(set(ids) - set(records.ids))
        if missing:
            raise UserError(_(
                'Some records no longer exist (%s); nothing was deleted.',
                ', '.join(str(i) for i in missing)))
        exempt = [rec.id for rec in records if not rec._audit_unlink_requires_reason]
        if exempt:
            raise UserError(_(
                'Record(s) %s are exempt from the Tier-1 delete gate and do '
                'not use this workflow; delete them directly.',
                ', '.join(str(i) for i in exempt)))
        records.check_access('unlink')
        return records

    def _target_ids(self):
        """Record ids from the list selection, falling back to the record id."""
        if self.res_ids:
            ids = []
            for part in self.res_ids.replace(';', ',').split(','):
                part = part.strip()
                if part:
                    ids.append(int(part))
            return ids
        ctx_ids = [rid for rid in (self.env.context.get('active_ids') or []) if rid]
        if ctx_ids:
            return list(ctx_ids)
        return [self.res_id] if self.res_id else []

    # ------------------------------------------------------------------ internal
    def _register(self):
        """Single registration point — only place the reason meets the service."""
        return self._register_for(self.model, self.res_id)

    def _register_for(self, model_name, res_id):
        from odoo.addons.sgc_offplan_rental_property_management.services import (
            sgc_audit_internal_service,
        )
        service = sgc_audit_internal_service.SgcAuditInternalService(self.env)
        return service.register_reason(model_name, res_id, self.reason)