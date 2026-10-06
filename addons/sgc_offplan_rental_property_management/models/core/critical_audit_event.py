# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

"""Critical-Change Audit — audit event (design §4, §7).

Append-only event record.  Every create/write/unlink from any caller that does
not present the module-internal bypass token raises AccessError (P0-2).  Only
``SgcAuditInternalService`` may create rows, and rows are never mutated after
creation (immutability P0-9).  ``_log_access=False``: no create/write metadata
columns exist, so there is no per-row audit metadata to forge or mutate.
"""

import logging
import uuid as uuid_lib

from odoo import api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

# Module-internal token (Rev 3 hardening, P0-2).  Generated in memory at import
# time, never stored, never serialized over RPC, never placed in env.context
# (the context is forgeable by any caller).  Exported for use by the internal
# service and by sibling protected models.
SGC_AUDIT_INTERNAL_TOKEN = uuid_lib.uuid4().hex

_GENESIS_HASH = '0' * 64

_SOURCE_TIER = {
    'ui': 1,
    'channel': 1,
    'import': 2,
    'rpc': 2,
    'cron': 2,
    'server_action': 2,
    'copy': 1,
    'archive': 2,
    'unarchive': 2,
    'unlink': 2,
    'wizard': 1,
    'system': 3,
}


class CriticalAuditEvent(models.Model):
    _name = 'sgc.critical.audit.event'
    _description = 'Critical Change Audit Event'
    _order = 'id desc'
    _log_access = False

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
        index=True,
    )
    tier = fields.Selection([('1', 'Tier 1'), ('2', 'Tier 2'), ('3', 'Tier 3')], string='Tier', index=True, required=True)
    operation = fields.Char(string='Operation', size=128, index=True, required=True)
    operation_label = fields.Char(string='Operation Label', size=256)
    model = fields.Char(string='Model', size=128, required=True, index=True)
    res_id = fields.Integer(string='Record ID', index=True, required=True)
    res_display_name = fields.Char(string='Record Display Name', size=256)
    user_id = fields.Many2one('res.users', string='User', index=True)
    tenant_uuid = fields.Char(string='Tenant UUID', size=36, index=True, required=True)
    company_id = fields.Many2one('res.company', string='Company', index=True, required=True)
    timestamp = fields.Datetime(string='Timestamp', index=True, required=True, default=fields.Datetime.now)
    correlation_uuid = fields.Char(string='Correlation UUID', size=36, index=True)
    request_id = fields.Char(string='Request ID', size=128)
    reason = fields.Text(string='Reason')
    reason_secret_detected = fields.Boolean(string='Reason Secret Detected')
    secret_pattern_detected = fields.Boolean(string='Secret Pattern Detected')
    old_value = fields.Json(string='Old Value')
    new_value = fields.Json(string='New Value')
    field_changes = fields.One2many('sgc.critical.audit.field.change', 'event_id', string='Field Changes')
    chatter_message_id = fields.Many2one('mail.message', string='Chatter Message', ondelete='set null', index=True)
    chain_no = fields.Integer(string='Chain No', index=True, required=True)
    prev_hash = fields.Char(string='Previous Hash', size=64, required=True, default=_GENESIS_HASH)
    row_hash = fields.Char(string='Row Hash', size=64, required=True)
    canonical_payload = fields.Text(
        string='Canonical Payload',
        readonly=True,
        help='The exact serialized payload hashed into row_hash at capture '
             'time. Verification hashes these stored bytes instead of '
             'reconstructing the payload from the row, because reconstruction '
             'is not byte-identical: the hash covers Python values (e.g. None) '
             'that a round-trip through this row does not preserve, and the '
             'field-change shape carries more keys than row readers rebuild. '
             'Canonical JSON serialization is not deterministic across '
             'implementations (see RFC 8785), so storing the bytes removes the '
             'need for two code paths to stay byte-identical forever. Holds '
             'already-redacted values only, so it adds no exposure beyond '
             'old_value/new_value/reason. Rows written before 2026-09-15 have '
             'this empty and cannot be attested.',
    )
    policy_version = fields.Integer(string='Policy Version', required=True, default=1)
    source = fields.Selection(
        [
            ('ui', 'UI'),
            ('channel', 'Channel'),
            ('import', 'Import'),
            ('rpc', 'RPC'),
            ('cron', 'Cron'),
            ('server_action', 'Server Action'),
            ('copy', 'Copy'),
            ('archive', 'Archive'),
            ('unarchive', 'Unarchive'),
            ('unlink', 'Unlink'),
            ('wizard', 'Wizard'),
            ('system', 'System'),
        ],
        string='Source',
        required=True,
        default='ui',
    )
    redaction_applied = fields.Boolean(string='Redaction Applied')
    schema_version = fields.Integer(string='Schema Version', required=True, default=2)
    ip_address = fields.Char(string='IP Address', size=45)
    user_agent = fields.Char(string='User Agent', size=128)

    _chain_no_unique_per_tenant_company = models.Constraint(
        'UNIQUE (tenant_uuid, company_id, chain_no)',
        'Chain number must be unique within a tenant/company chain.',
    )

    # ------------------------------------------------------------------ computed
    @api.depends('tier', 'operation', 'model', 'res_id')
    def _compute_name(self):
        for event in self:
            event.name = '[TIER%s] %s - %s #%s' % (
                event.tier, event.operation, event.model, event.res_id,
            )

    _default_source_tier = _SOURCE_TIER

    # ------------------------------------------------------------- P0-2 boundary
    def create(self, vals_list, **kwargs):
        token = kwargs.pop('_sgc_internal_token', None)
        if token != SGC_AUDIT_INTERNAL_TOKEN:
            raise AccessError(
                'Audit events are append-only and can only be created by the internal audit service.'
            )
        # Odoo's O2M machinery materializes `field_changes` command rows via
        # comodel.create() WITHOUT kwargs, which would trip the field-change
        # model's token guard (AccessError).  Create the parent events first,
        # then the child rows directly with an explicit token and event_id.
        # Same transaction, so a child failure rolls back the parents
        # (fail-closed, C1); the token never enters env.context.
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        child_row_sets = []
        for vals in vals_list:
            commands = vals.pop('field_changes', None) or []
            child_row_sets.append([
                cmd[2] for cmd in commands
                if isinstance(cmd, (tuple, list)) and len(cmd) >= 3 and cmd[0] == 0
            ])
        events = super().create(vals_list)
        for event, rows in zip(events, child_row_sets):
            if rows:
                self.env['sgc.critical.audit.field.change'].create(
                    [{**row, 'event_id': event.id} for row in rows],
                    _sgc_internal_token=token,
                )
        return events

    def write(self, vals, **kwargs):
        token = kwargs.pop('_sgc_internal_token', None)
        if token != SGC_AUDIT_INTERNAL_TOKEN:
            raise AccessError('Audit events are immutable.')
        return super().write(vals)

    def unlink(self, **kwargs):
        token = kwargs.pop('_sgc_internal_token', None)
        if token != SGC_AUDIT_INTERNAL_TOKEN:
            raise AccessError('Audit events are append-only and cannot be deleted.')
        return super().unlink()

    def copy(self, default=None):
        raise AccessError('Audit events cannot be copied.')

    # --------------------------------------------------- source-record access
    def action_open_source_record(self):
        """Open the current source record (§9 [C4]).

        Subject to the viewer's normal record permissions: a viewer without
        read access on the source model gets AccessError from the action
        resolution itself.  The visit is itself logged as a Tier-2 event
        (operation ``source_record_viewed``, no reason required [C11]).

        The event log and the action are produced in the SAME transaction;
        if the audit write fails the action fails (fail-closed, C1).
        """
        self.ensure_one()
        if not self.model:
            raise AccessError('This audit event has no source model to open.')
        source_model = self.env.get(self.model)
        if source_model is None:
            raise AccessError(
                'The source model %r is no longer installed.' % self.model
            )
        # Log the visit first; same transaction as the returned action.
        from odoo.addons.sgc_offplan_rental_property_management.services import (
            sgc_audit_internal_service,
        )
        service = sgc_audit_internal_service.SgcAuditInternalService(self.env)
        service.capture_event(
            tier='2',
            operation='source_record_viewed',
            operation_label='Source record opened from audit trail',
            model=self.model,
            res_id=self.res_id,
            res_display_name=None,
            field_changes=[],
            source='ui',
            correlation_uuid=self.correlation_uuid,
        )
        return {
            'type': 'ir.actions.act_window',
            'res_model': self.model,
            'res_id': self.res_id,
            'view_mode': 'form',
            'target': 'current',
        }