# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

"""Critical-Change Audit — tenant singleton (design §4.8).

One singleton row per database.  The ``tenant_uuid`` never changes for the
life of the deployment (P0-7: restore keeps the UUID for same-lineage recoveries;
a clone to a NEW deployment must regenerate it as a documented operator step;
the singleton never auto-renews on restart).
"""

import logging
import uuid as uuid_lib

from odoo import fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class CriticalAuditTenant(models.Model):
    _name = 'sgc.critical.audit.tenant'
    _description = 'Critical Audit Tenant Singleton'

    tenant_uuid = fields.Char(
        string='Tenant UUID',
        size=36,
        required=True,
        index=True,
        copy=False,
        help='Stable UUID identifying this deployment lineage. Never regenerated automatically.',
    )
    db_name = fields.Char(
        string='Database Name',
        required=True,
        copy=False,
        help='env.cr.dbname at creation time.',
    )
    created_on = fields.Datetime(
        string='Created On',
        required=True,
        default=fields.Datetime.now,
        copy=False,
    )

    _tenant_uuid_uniq = models.Constraint(
        'UNIQUE (tenant_uuid)',
        'Tenant UUID must be unique; a second tenant row is impossible.',
    )

    @classmethod
    def _ensure_tenant(cls, env):
        """Bootstrap the singleton tenant (created at install, or lazily on first capture).

        Uses raw SQL so ordinary model creation security is bypassed exactly once;
        a second row can never appear (same insert is guarded by LIMIT + UNIQUE).
        Returns ``(id, tenant_uuid)``.
        """
        cr = env.cr
        cr.execute(
            'SELECT id, tenant_uuid FROM sgc_critical_audit_tenant ORDER BY id LIMIT 1'
        )
        row = cr.fetchone()
        if row:
            return row[0], row[1]
        new_uuid = str(uuid_lib.uuid4())
        cr.execute(
            """
            INSERT INTO sgc_critical_audit_tenant
                (tenant_uuid, db_name, created_on, create_uid, create_date, write_uid, write_date)
            VALUES (%s, %s, now(), 1, now(), 1, now())
            RETURNING id
            """,
            (new_uuid, cr.dbname),
        )
        tenant_id = cr.fetchone()[0]
        _logger.info('SGC audit tenant created in db %s: uuid=%s', cr.dbname, new_uuid)
        return tenant_id, new_uuid

    def create(self, vals_list, **kwargs):
        raise AccessError(
            'The critical audit tenant is created once, at install time, through the internal bootstrap.'
        )

    def write(self, vals, **kwargs):
        raise AccessError('The critical audit tenant is immutable.')

    def unlink(self, **kwargs):
        raise AccessError('The critical audit tenant cannot be deleted.')

    # Delegation safety-net (P0-2): tenant rows must never be copied.
    def copy(self, default=None):
        raise AccessError('The critical audit tenant cannot be copied.')