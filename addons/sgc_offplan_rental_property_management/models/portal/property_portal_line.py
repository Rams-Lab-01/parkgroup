# -*- coding: utf-8 -*-
from odoo import fields, models


class PropertyPortalLine(models.Model):
    _name = "property.portal.line"
    _inherit = ['sgc.critical.audit.mixin']
    _description = "Per-portal listing status"
    _order = "portal_id, property_id"

    # Entry 53 capture scope: listing identity, publication state and sync
    # outcome. Line model -> delete-gate exempt.
    _audit_watched_fields = frozenset({
        'property_id', 'portal_id', 'external_id', 'status',
        'last_sync', 'last_error', 'payload_hash',
    })
    _audit_unlink_requires_reason = False

    property_id = fields.Many2one("property.details", required=True, ondelete="cascade")
    portal_id = fields.Many2one("portal.connector", required=True, ondelete="cascade")
    external_id = fields.Char(
        string="Portal Reference",
        index=True,
        help="Unique identifier assigned by the portal"
    )
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending"),
            ("published", "Published"),
            ("failed", "Failed"),
            ("disabled", "Disabled"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    last_sync = fields.Datetime()
    last_error = fields.Text()
    payload_hash = fields.Char(help="Hash of last synced payload to avoid unnecessary pushes.")

    _check_property_portal_unique = models.Constraint(
        'unique(property_id, portal_id)',
        'Portal entry already exists for this property.',
    )
    _check_external_portal_unique = models.Constraint(
        'unique(external_id, portal_id)',
        'External reference already exists for this portal.',
    )
