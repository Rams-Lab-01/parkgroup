# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from odoo import api, fields, models, _


class PropertyWebsiteInquiry(models.Model):
    """Make the public website inquiry a first-class entry point of the journey.

    Historically the controller created a bare ``crm.lead`` with no
    ``property_id`` and no back-link, so the lead could not be traced to the
    unit the visitor actually asked about. This guarantees, for every inquiry
    regardless of caller: a linked lead, with the property attached, and the
    inquiry's ``lead_id`` populated (both directions).
    """
    _inherit = "property.website.inquiry"

    @api.model_create_multi
    def create(self, vals_list):
        inquiries = super().create(vals_list)
        inquiries._ensure_lead_link()
        return inquiries

    def _ensure_lead_link(self):
        for inquiry in self:
            if inquiry.lead_id:
                continue
            inquiry.lead_id = inquiry._get_or_create_lead().id

    def _get_or_create_lead(self):
        """Reuse an existing open lead for the same email+property (so a repeat
        visitor is one opportunity, not a duplicate), else create one carrying
        the property_id that ties it to the unit."""
        self.ensure_one()
        Lead = self.env["crm.lead"].sudo()
        lead = Lead.search([
            ("email_from", "=", self.email),
            ("property_id", "=", self.property_id.id),
            ("active", "=", True),
        ], limit=1)
        if not lead:
            lead = Lead.create({
                "name": _("Property inquiry: %s") % (
                    self.property_id.name or _("Property")),
                "contact_name": self.name,
                "email_from": self.email,
                "phone": self.phone or False,
                "description": self.message or _(
                    'Website inquiry for "%s".'
                ) % (self.property_id.name or ""),
                "property_id": self.property_id.id,
            })
        return lead
