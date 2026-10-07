# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template (reconciled build, 2026-08-31).
#
# Brief §2.15 — answers "are WhatsApp conversations currently logged
# anywhere, or only on individual phones?" Captures WhatsApp
# conversations, both inbound and outbound, regardless of whether
# the legacy workflow saves them anywhere.
#
# Body content is REDACTED — the model stores `body_redacted`, not
# raw message bodies, to keep PII handling explicit and so that any
# downstream AI / archival path can opt in to richer capture by
# adding a separate consent-gated extension.
#
# Constraint #4 model name: `sgc.wa_log`.
from odoo import _, api, fields, models


class SgcWaLog(models.Model):
    _name = "sgc.wa_log"
    _description = "WhatsApp conversation log (per-tenant)"
    _order = "timestamp desc, id"
    _rec_name = "display_name"

    tenant_id = fields.Many2one(
        # No tracking=True: this model does not inherit mail.thread, so Odoo
        # accepts the parameter and then silently ignores it (warning on every
        # registry load). See the class docstring -- deliberately not adding
        # mail.thread, because this is a high-volume ingest log.
        "sgc.brokerage.tenant",
        required=True, check_company=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        help="Counterparty — the contact whose phone number received "
             "or sent the message.",
    )
    bsp_provider = fields.Selection(
        selection=[
            ("twilio", "Twilio"),
            ("messagebird", "MessageBird"),
            ("unifonic", "Unifonic"),
            ("gupshup", "Gupshup"),
            ("meta", "Meta Cloud API"),
            ("other", "Other"),
        ],
        required=True, index=True,
        help="Brief 2.13 — which WhatsApp BSP delivered this message. "
             "Per-tenant default is set on `sgc.brokerage.tenant."
             "wa_bsp_provider` and copied to this row at ingest.",
    )
    direction = fields.Selection(
        selection=[
            ("in", "Inbound"),
            ("out", "Outbound"),
        ],
        required=True, index=True,
    )
    timestamp = fields.Datetime(required=True, index=True)
    body_redacted = fields.Text(
        help="Message body, REDACTED for PII. Consumers needing raw "
             "bodies should build a separate opt-in addon that gates "
             "on `ir.config_parameter('sgc.wa_log.raw_storage')`.",
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        help="Multimedia attached to this message — voice note, image, "
             "PDF brochure, etc. Uses the polymorphic res_model/res_id "
             "pattern per Constraint #6.",
    )
    external_id = fields.Char(
        index=True,
        help="BSP-specific message identifier (e.g. Twilio "
             "`MessageSid`). Useful for de-duplication and trace.",
    )
    lead_id = fields.Many2one(
        "crm.lead",
        help="Optional — the CRM lead the conversation is bound to.",
    )

    display_name = fields.Char(
        compute="_compute_display_name", store=True, readonly=True,
    )

    _sgc_wa_log_external_id_unique = models.Constraint(
        "unique(tenant_id, bsp_provider, external_id)",
        "Each BSP message identifier must be unique per (tenant, "
        "provider) — protects against double-ingest.",
    )

    @api.depends("direction", "partner_id", "timestamp")
    def _compute_display_name(self):
        for w in self:
            w.display_name = "{}/{} @ {}".format(
                w.direction,
                w.partner_id.display_name if w.partner_id else "?",
                w.timestamp or "",
            )
