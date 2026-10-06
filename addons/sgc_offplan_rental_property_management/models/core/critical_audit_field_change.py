# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

"""Critical-Change Audit — per-field change row (design §4.3).

Child rows of ``sgc.critical.audit.event``.  Values stored here are already
redacted (per §11) before being written; the ``redacted`` flag mirrors a masked
value for the UI (•••••) and the boolean is used by verification.  Same
immutability contract as the parent event (P0-9).
"""

from odoo import fields, models
from odoo.exceptions import AccessError

from .critical_audit_event import SGC_AUDIT_INTERNAL_TOKEN


class CriticalAuditFieldChange(models.Model):
    _name = 'sgc.critical.audit.field.change'
    _description = 'Critical Change Audit Field Change'
    _log_access = False

    event_id = fields.Many2one(
        'sgc.critical.audit.event',
        string='Event',
        required=True,
        index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='event_id.company_id',
        store=True,
        index=True,
        help='Inherited from the parent event for company-scoped record rules (§5.4).',
    )
    field_name = fields.Char(string='Field Name', size=128)
    field_label = fields.Char(string='Field Label', size=256)
    old_value = fields.Text(string='Old Value')
    new_value = fields.Text(string='New Value')
    redacted = fields.Boolean(string='Redacted')
    secret_detected = fields.Boolean(string='Secret Detected')

    # ------------------------------------------------------------- P0-2/P0-9
    def create(self, vals_list, **kwargs):
        token = kwargs.pop('_sgc_internal_token', None)
        if token != SGC_AUDIT_INTERNAL_TOKEN:
            raise AccessError(
                'Audit field-change rows can only be created by the internal audit service.'
            )
        return super().create(vals_list)

    def write(self, vals, **kwargs):
        token = kwargs.pop('_sgc_internal_token', None)
        if token != SGC_AUDIT_INTERNAL_TOKEN:
            raise AccessError('Audit field-change rows are immutable.')
        return super().write(vals)

    def unlink(self, **kwargs):
        token = kwargs.pop('_sgc_internal_token', None)
        if token != SGC_AUDIT_INTERNAL_TOKEN:
            raise AccessError('Audit field-change rows are append-only and cannot be deleted.')
        return super().unlink()

    def copy(self, default=None):
        raise AccessError('Audit field-change rows cannot be copied.')