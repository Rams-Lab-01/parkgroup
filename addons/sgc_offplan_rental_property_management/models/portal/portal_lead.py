# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import email_normalize
import re


class PortalLead(models.Model):
    _name = "portal.lead"
    _description = "Lead captured from property portals"
    _inherit = ["mail.thread", "mail.activity.mixin", "sgc.critical.audit.mixin"]
    _order = "create_date desc"

    name = fields.Char(string="Lead Name", required=True, tracking=True)
    email = fields.Char(tracking=True)
    phone = fields.Char(tracking=True)
    message = fields.Text()

    portal_id = fields.Many2one(
        "portal.connector", 
        required=True, 
        ondelete="restrict",
        help="Portal from which this lead originated"
    )
    listing_line_id = fields.Many2one("property.portal.line", ondelete="set null")
    property_id = fields.Many2one(related="listing_line_id.property_id", store=True)

    state = fields.Selection(
        [
            ("new", "New"),
            ("contacted", "Contacted"),
            ("qualified", "Qualified"),
            ("lost", "Lost"),
            ("won", "Won"),
        ],
        default="new",
        tracking=True,
        index=True,
    )
    received_at = fields.Datetime(
        default=fields.Datetime.now,
        index=True,
        help="Date and time when the lead was received"
    )

    def action_mark_contacted(self):
        self.write({"state": "contacted"})

    def action_mark_qualified(self):
        self.write({"state": "qualified"})

    def action_mark_lost(self):
        self.write({"state": "lost"})

    def action_mark_won(self):
        self.write({"state": "won"})

    @api.constrains("email")
    def _check_email_format(self):
        """Validate email format"""
        for lead in self:
            if lead.email:
                try:
                    email_normalize(lead.email)
                except Exception:
                    raise ValidationError(
                        _("Invalid email format: %s") % lead.email
                    )

    @api.constrains("phone")
    def _check_phone_format(self):
        """Validate phone number format"""
        for lead in self:
            if lead.phone:
                # Remove spaces, dashes, parentheses
                clean_phone = re.sub(r"[^\d+]", "", lead.phone)
                if len(clean_phone) < 7:
                    raise ValidationError(
                        _("Phone number too short: %s") % lead.phone
                    )
