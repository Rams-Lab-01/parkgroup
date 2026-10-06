# -*- coding: utf-8 -*-
from odoo import fields, models


class XmlFeedConfig(models.Model):
    _name = "xml.feed.config"
    _inherit = ['sgc.critical.audit.mixin']
    _description = "XML Feed Configuration"

    # Entry 52 scope: feed configuration is contract-like, so it keeps the gate.
    _audit_watched_fields = frozenset({
        'name', 'portal_id', 'version', 'enabled', 'notes',
    })

    name = fields.Char(required=True)
    portal_id = fields.Many2one("portal.connector", required=True, ondelete="cascade")
    version = fields.Selection([
        ("v1", "Version 1"),
        ("v2", "Version 2"),
        ("v3", "Version 3"),
    ], default="v3")
    enabled = fields.Boolean(default=True)
    notes = fields.Text()
