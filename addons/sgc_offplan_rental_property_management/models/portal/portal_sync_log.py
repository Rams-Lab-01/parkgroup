# -*- coding: utf-8 -*-
from odoo import fields, models


class PortalSyncLog(models.Model):
    _name = "portal.sync.log"
    _inherit = ['sgc.critical.audit.mixin']
    _description = "Portal Sync Log"
    _order = "started_at desc"

    # Entry 52 scope: counters and outcome; the free message may echo feed
    # payload fragments, so it stays out. Operational log -> gate exempt.
    _audit_watched_fields = frozenset({
        'portal_id', 'status', 'started_at', 'finished_at', 'created_count',
        'updated_count', 'failed_count', 'duration_seconds',
    })
    _audit_unlink_requires_reason = False

    portal_id = fields.Many2one("portal.connector", required=True, ondelete="cascade")
    started_at = fields.Datetime(default=fields.Datetime.now, required=True)
    finished_at = fields.Datetime()
    status = fields.Selection(
        [
            ("success", "Success"),
            ("partial", "Partial Success"),
            ("failed", "Failed"),
        ],
        default="success",
        required=True,
    )
    message = fields.Text()
    created_count = fields.Integer()
    updated_count = fields.Integer()
    failed_count = fields.Integer()
    duration_seconds = fields.Float()
