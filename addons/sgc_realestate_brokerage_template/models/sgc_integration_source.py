# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template (reconciled build, 2026-08-31).
#
# Brief §2.11 — answers the "what CRM / PM software / ERP is the
# brokerage using today" question. One row per external system the
# tenant declares it depends on.
#
# Constraint #4 model name: `sgc.integration.source` (no parallel
# definitions; this is the canonical).
from odoo import _, api, fields, models


class SgcIntegrationSource(models.Model):
    _name = "sgc.integration.source"
    _description = "External system declared as a tenant dependency"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "sequence, system"
    _rec_name = "system"

    tenant_id = fields.Many2one(
        "sgc.brokerage.tenant", required=True, check_company=True,
        tracking=True,
    )
    sequence = fields.Integer(default=10)
    system = fields.Selection(
        selection=[
            ("crm", "CRM (Salesforce / HubSpot / Zoho / in-house)"),
            ("pm_software", "Property-management software"),
            ("erp_accounting", "ERP / accounting"),
            ("communication", "Communication (telephony / Slack / Teams)"),
            ("portal_bayut", "Bayut portal"),
            ("portal_propertyfinder", "Property Finder portal"),
            ("portal_dubizzle", "Dubizzle / OLX portal"),
            ("meta_ads", "Meta Ads (Facebook/Instagram)"),
            ("google_ads", "Google Ads"),
            ("whatsapp_bsp", "WhatsApp Business Solution Provider"),
            ("dld_partner", "DLD data-scrapping partner"),
            ("bank_stmt", "Bank statement source"),
            ("other", "Other"),
        ],
        required=True, index=True,
        help="External system the tenant declares it depends on, BEFORE "
             "Phase-1 cutover. Used by the migration source-map (see "
             "`sgc.migration.source_map`) and by the SGC audit plugin's "
             "compatibility report.",
    )
    vendor_name = fields.Char(
        help="Free-text — the vendor name (e.g. 'HubSpot', 'Zoho CRM "
             "Enterprise', 'Sage 50') for audit-trail clarity.",
    )
    version = fields.Char(
        help="Software version (e.g. 'v12.0'). Used to scope any "
             "compatibility notes during the migration plan.",
    )
    data_owner_field = fields.Char(
        help="Field on the external system's master record that the "
             "brokerage relies on for ownership (used by Phase-1 "
             "migration to scope who-creates-what).",
    )
    last_synced_at = fields.Datetime(readonly=True)
    notes = fields.Text()

    _sgc_integration_source_unique = models.Constraint(
        "unique(tenant_id, system, vendor_name)",
        "Only one row per tenant per (system, vendor) — collapse "
        "duplicate declarations.",
    )
