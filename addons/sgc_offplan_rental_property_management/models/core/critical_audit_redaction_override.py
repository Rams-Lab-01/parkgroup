# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

"""Critical-Change Audit — per-company redaction override (design §11).

An override row is the ONLY way to change how a critical field is redacted for
a company.  Resolution order at capture time: override -> baseline -> fail-closed
default (REDACTED_FULL for observed critical fields).  No company_id=False
shareable override exists ([C7]); committing the override in a new company
requires a new row.  Every override mutation emits an audit event with
operation ``redaction_override_change``.
"""

import logging

from odoo import fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class CriticalAuditRedactionOverride(models.Model):
    _name = 'sgc.critical.audit.redaction.override'
    _description = 'Critical Audit Redaction Override'
    _rec_name = 'field_name'

    company_id = fields.Many2one('res.company', string='Company', required=True, index=True, ondelete='cascade')
    model = fields.Char(string='Model', required=True)
    field_name = fields.Char(string='Field Name', required=True)
    redaction_class = fields.Selection(
        [
            ('NOT_REDACTED', 'Not Redacted'),
            ('REDACTED_PARTIAL', 'Redacted Partial'),
            ('REDACTED_FULL', 'Redacted Full'),
            ('SECRET_SCAN', 'Secret Scan'),
        ],
        string='Redaction Class',
        required=True,
    )
    reason = fields.Text(string='Reason')
    policy_version = fields.Integer(string='Policy Version', default=1, required=True, readonly=True)

    _override_unique_per_company_model_field = models.Constraint(
        'UNIQUE (company_id, model, field_name)',
        'An override already exists for this company/model/field.',
    )

    # ------------------------------------------------------------- validation
    def _validate_target(self):
        for rec in self:
            if not rec.company_id:
                raise ValidationError('A redaction override must belong to a company ([C7]).')
            model_obj = self.env['ir.model'].sudo().search([('model', '=', rec.model)], limit=1)
            if not model_obj:
                raise ValidationError('Unknown model %r for redaction override.' % rec.model)
            model_class = self.env.get(rec.model)
            if model_class is None or rec.field_name not in model_class._fields:
                raise ValidationError(
                    'Field %r does not exist on model %r for redaction override.'
                    % (rec.field_name, rec.model)
                )

    def create(self, vals_list):
        records = super().create(vals_list)
        records._validate_target()
        for rec in records:
            self._emit_override_event(rec, 'create', old=None, new=vars_values(rec))
        return records

    def write(self, vals):
        old_vals = {rec.id: vars_values(rec) for rec in self}
        res = super().write(vals)
        self._validate_target()
        # policy_version auto-bumps on every change (§11).
        for rec in self:
            rec.policy_version = (rec.policy_version or 0) + 1
        for rec in self:
            self._emit_override_event(rec, 'write', old=old_vals.get(rec.id), new=vars_values(rec))
        return res

    def unlink(self):
        for rec in self:
            self._emit_override_event(rec, 'unlink', old=vars_values(rec), new=None)
        return super().unlink()

    # ------------------------------------------------------------- event sink
    def _emit_override_event(self, rec, operation, old, new):
        """Emit the redaction_override_change audit event (best-effort, in tx).

        Runs through the internal service so the event honors the token boundary;
        a failure is logged and re-raised by the caller's transaction (fail closed).
        """
        try:
            from odoo.addons.sgc_offplan_rental_property_management.services import (
                sgc_audit_internal_service,
            )
            service = sgc_audit_internal_service.SgcAuditInternalService(self.env)
            service.capture_override_change(
                override=rec,
                operation=operation,
                old_values=old or {},
                new_values=new or {},
            )
        except Exception as err:
            _logger.error('Failed to emit redaction_override_change event: %s', err, exc_info=True)
            raise


def vars_values(rec):
    """Snapshot of the four policy-bearing display fields (never secrets)."""
    return {
        'company_id': rec.company_id.id,
        'model': rec.model,
        'field_name': rec.field_name,
        'redaction_class': rec.redaction_class,
    }