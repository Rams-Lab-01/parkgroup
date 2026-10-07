# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template (reconciled build, 2026-08-31).
#
# Constraint #2 of the SGC ADDON ESTATE RECONCILIATION brief:
#
#     sgc.brokerage.tenant already exists as the multi-tenant anchor.
#     All new tenant-level fields (brand_positioning, wa_bsp_provider,
#     dld_partner_id, trakheesi_account_id, uaedds_enabled,
#     strategy_risk_tolerance, founder_pain_point, licensable) must be
#     added via _inherit on this model — do not create a parallel tenant
#     model.
#
# Therefore this module EXTENDS the existing sgc.brokerage.tenant defined
# in `sgc_brokerage_tenant.py` of the same addon. No new _name is declared.
#
# Constraint #5: never hardcode URLs / emails / API endpoints — every
# tenant-level credential lives on this tenant record, not in XML data
# and not as an `ir.config_parameter` global. Default values are *empty*
# (not localhost, not literal example emails).
#
# Commission logic is OUT OF SCOPE per Constraint #3 — see the TODO at
# the bottom of this file. sgc_commission remains `30_QUARANTINE/`-held
# and UNRESOLVED per `docs/audit/MODULE_PROVENANCE.md`; nothing here
# references or duplicates it.
from odoo import _, api, fields, models


class SgcBrokerageTenantReconcile(models.Model):
    """Reconciled extension of `sgc.brokerage.tenant`.

    Document source: `docs/research/DATA_EXTRACTION_NEXTGEN_PLATFORM_2026-08-31.md`,
    Appendix A ("machine-readable number-summary table"). Each field added
    below corresponds to one or more brief items (1.21, 1.23, 2.13, 2.14,
    2.18, 2.30, 2.32, 2.33) whose answers are `unknown` to SGC and must
    be supplied by the brokerage's operations team at onboarding time.
    """

    _inherit = "sgc.brokerage.tenant"

    # ------------------------------------------------------------------
    # Brief §4.21 — current brand positioning
    # ------------------------------------------------------------------
    brand_positioning = fields.Selection(
        selection=[
            ("luxury", "Luxury"),
            ("mid_market", "Mid-market"),
            ("investment", "Investment-focused"),
            ("end_user", "End-user"),
            ("mixed", "Mixed"),
        ],
        required=False,
        tracking=True,
        help="Brief 4.21 — strategic positioning of the tenant. Drives "
             "marketing-copy tone in the growth kit (Phase 4) and the "
             "default landing-page hero text.",
    )

    # ------------------------------------------------------------------
    # Brief §2.13 — WhatsApp BSP provider (the third-party service the
    # tenant uses to send/receive WhatsApp messages from a business number)
    # ------------------------------------------------------------------
    wa_bsp_provider = fields.Selection(
        selection=[
            ("twilio", "Twilio"),
            ("messagebird", "MessageBird"),
            ("unifonic", "Unifonic (UAE region)"),
            ("gupshup", "Gupshup"),
            ("meta", "Meta Cloud API"),
            ("other", "Other"),
        ],
        required=False,
        tracking=True,
        help="Brief 2.13 — per-tenant WhatsApp Business Solution Provider. "
             "Each provider has its own adapter under sgc.wa_log; "
             "see `sgc_wa_log.py` for the unified log shape.",
    )

    # ------------------------------------------------------------------
    # Brief §2.14 — Trakheesi / DLD portal access. The DLD does not
    # publish a public REST API; typical integration is via the DLD
    # Data-Scrapping-Partner programme. We persist the *partner ID*
    # and the per-tenant Trakheesi account in fields only — credentials
    # are NEVER stored as plain text (use res.config.settings instead).
    # ------------------------------------------------------------------
    dld_partner_id = fields.Char(
        required=False,
        help="Brief 2.14 — DLD data-scrapping-partner identifier "
             "issued to the brokerage. Stored as opaque string; the "
             "credential itself lives in `res.config.settings`.",
    )
    dld_partner_secret_setting = fields.Char(
        required=False,
        help="Auditor-facing reference to the `res.config_settings` key "
             "where the DLD-partner secret is stored. NEVER the secret "
             "itself — leave this blank in any seed XML and populate "
             "via the Settings UI.",
    )
    trakheesi_account_id = fields.Char(
        required=False,
        help="Brief 2.14 — Trakheesi advertiser/agent account identifier "
             "issued to the brokerage.",
    )

    # ------------------------------------------------------------------
    # Brief §2.18 — UAEDDS (UAE Direct Debit System) usage
    # ------------------------------------------------------------------
    uaedds_enabled = fields.Boolean(
        default=False,
        tracking=True,
        help="Brief 2.18 — UAEDDS may not be enabled absent an explicit "
             "consent record. Default is False; the onboarding wizard "
             "(sibling addon) must surface a confirmation step before "
             "this can be flipped to True.",
    )
    uaedds_enabled_consent_at = fields.Datetime(
        readonly=True,
        help="Timestamp of the explicit per-tenant UAEDDS consent. "
             "Left blank until `uaedds_enabled` is flipped.",
    )

    # ------------------------------------------------------------------
    # Brief §2.30 — internal vs. licensable
    # ------------------------------------------------------------------
    licensable = fields.Boolean(
        default=False,
        tracking=True,
        help="Brief 2.30 — True if the tenant has explicit licensing "
             "rights to sub-license the platform to other brokerages. "
             "False for an internally-used brokerage; True for tenants "
             "that resell the platform. Affects the SaaS TOS template "
             "and the data-isolation SLA.",
    )

    # ------------------------------------------------------------------
    # Brief §2.32 — risk tolerance
    # ------------------------------------------------------------------
    strategy_risk_tolerance = fields.Selection(
        selection=[
            ("validate_small", "Validate small first"),
            ("phased_commit", "Phased commit"),
            ("full_build", "Full build from the outset"),
        ],
        required=False,
        tracking=True,
        help="Brief 2.32 — risk posture SGC recommended: `validate_small` "
             "(Starter-tier pilot, 60 days, single pre-vetted tenant, "
             "pre-agreed Phase 8 closure). See `docs/REAL_ESTATE_BROKERAGE_"
             "ROLLOUT.md` §Phase 0.",
    )

    # ------------------------------------------------------------------
    # Brief §2.33 — founder pain point (single, daily-felt)
    # ------------------------------------------------------------------
    founder_pain_point = fields.Text(
        required=False,
        help="Brief 2.33 — the single most painful daily operational pain "
             "the founder has not yet seen addressed. This field is a "
             "placeholder that re-prompting per onboarding (and per "
             "quarterly review) is expected to populate. See "
             "`DATA_EXTRACTION_NEXTGEN_PLATFORM_2026-08-31.md` §2.33.",
    )
    founder_pain_point_log_ids = fields.One2many(
        "sgc.brokerage.incident",
        "tenant_id",
        domain=[("category", "=", "founder_pain")],
        string="Founder-pain incident log",
        help="Read-only convenience: incidents recorded as founder-pain "
             "category tied to this tenant. Populated by `sgc.brokerage."
             "incident` rows; never the primary input.",
    )

    # ------------------------------------------------------------------
    # Cross-cutting: re-declarations of any blank defaults are
    # forbidden. Validation at the model level.
    # ------------------------------------------------------------------

    @api.constrains("uaedds_enabled")
    def _check_uaedds_consent(self):
        for tenant in self:
            if tenant.uaedds_enabled and not tenant.uaedds_enabled_consent_at:
                raise ValueError(_(
                    "Tenant %(code)s: UAEDDS cannot be enabled without a "
                    "recorded consent timestamp. Set "
                    "`uaedds_enabled_consent_at` first.",
                    code=tenant.code,
                ))

    # ------------------------------------------------------------------
    # TODO (per SGC ADDON ESTATE RECONCILIATION constraint #3):
    #
    #   - Commission logic is OUT OF SCOPE for this build.
    #   - sgc_commission is `30_QUARANTINE/`-held (Phase 9 UNRESOLVED).
    #   - When counsel signs off per
    #     `30_QUARANTINE/sgc_lead_scoring.md` resolution path,
    #     commission fields would be added via a sibling module
    #     `sgc_realestate_brokerage_commission` that inherits
    #     sgc_commission.* models — NOT HERE.
    # ------------------------------------------------------------------
