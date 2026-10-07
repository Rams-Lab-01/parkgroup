# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template (reconciled build, 2026-08-31).
#
# Constraint #1 of the SGC ADDON ESTATE RECONCILIATION brief:
#
#     Check for sgc_offplan_rental_property_management.property.unit.
#     If found, re.unit must _inherit that model, not replace it.
#     If not confirmed present, generate the standalone model as originally
#     specified, but wrap the class with a comment:
#
#         "SGC OPR model not found in this environment — standalone
#          fallback active; merge with OPR model once confirmed present."
#
# A `find` over `sgc_offplan_rental_property_management/models/` shows
# the OPR module defines `property.project`, `property.sub.project`,
# `property.details` (the unit/listing record) — but NO
# `property.unit` model exists in this environment. The fallback below
# is therefore active.
#
# When `property.unit` is later confirmed (or a future OPR release adds
# it), change `_name = 're.unit'` to `_inherit = 'property.unit'`
# (with model-class body unchanged) and remove the standalone fallback
# comment below. Until then, `re.unit` is the canonical per-tenant
# unit/property record for the brokerage template.
from odoo import _, api, fields, models


class ReUnit(models.Model):
    """Standalone fallback unit/property record. Per the docstring above,
    awaiting OPR's `property.unit` model to be confirmed present. Until
    then this is the canonical unit record used by the brokerage template.
    """

    # SGC OPR model not found in this environment — standalone fallback
    # active; merge with OPR model once confirmed present.
    _name = "re.unit"
    _description = "Real-estate unit (standalone fallback)"
    _inherit = [
        "mail.thread",
        "mail.activity.mixin",
    ]
    _order = "sequence, name"
    _check_company_auto = True
    _rec_name = "name"

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------
    name = fields.Char(
        required=True, index=True,
        help="Display name (e.g. 'Marina Heights — Unit 1204').",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    tenant_id = fields.Many2one(
        "sgc.brokerage.tenant",
        required=True,
        check_company=True,
        tracking=True,
        help="Owning tenant. Multi-tenant anchor per Constraint #2.",
    )
    # NOTE: `check_company=True` removed — this field's comodel IS
    # `res.company` itself, and Odoo's check_company domain assumes the
    # comodel has its own `company_id` field to cross-check against
    # (which `res.company` does not have). See the identical fix and
    # explanation in `sgc_brokerage_tenant.py`.
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda s: s.env.company,
    )

    # ------------------------------------------------------------------
    # Type / area
    # ------------------------------------------------------------------
    unit_type = fields.Selection(
        selection=[
            ("apartment", "Apartment"),
            ("villa", "Villa"),
            ("townhouse", "Townhouse"),
            ("office", "Office"),
            ("retail", "Retail"),
            ("warehouse", "Warehouse"),
            ("land", "Land"),
            ("other", "Other"),
        ],
        required=True,
        tracking=True,
        help="Brief 1.5 inventory breakdown categories.",
    )
    area_sqft = fields.Float(string="Area (sqft)")
    area_sqm = fields.Float(
        string="Area (sqm)",
        help="Helper field — auto-derived from `area_sqft` if empty.",
    )
    bedrooms = fields.Integer()
    bathrooms = fields.Integer()

    # ------------------------------------------------------------------
    # Geographic
    # ------------------------------------------------------------------
    community = fields.Char(
        index=True,
        help="Brief 4.19 — community / district name. Indexed for "
             "the predictive signal engine (Brief §29 layer 1).",
    )
    city = fields.Char(index=True)
    country_id = fields.Many2one("res.country")

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    state = fields.Selection(
        selection=[
            ("available", "Available"),
            ("reserved", "Reserved"),
            ("under_offer", "Under offer"),
            ("sold", "Sold"),
            ("leased", "Leased"),
            ("off_market", "Off-market"),
            ("archived", "Archived"),
        ],
        default="available", required=True, tracking=True,
    )

    # ------------------------------------------------------------------
    # Pricing
    # ------------------------------------------------------------------
    list_price_aed = fields.Monetary(
        string="List price (AED)", currency_field="currency_id",
    )
    currency_id = fields.Many2one(
        "res.currency", related="company_id.currency_id", readonly=True,
    )
    rent_monthly_aed = fields.Monetary(
        string="Monthly rent (AED)", currency_field="currency_id",
    )

    # ------------------------------------------------------------------
    # Brief §1.5 — units-under-active-management counts.
    # The aggregated count per tenant is computed by the
    # `_compute_tenant_unit_breakdown` triggered cron and stored on
    # `sgc.brokerage.tenant` as JSON. We do NOT cache it here.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # List-date accounting for Brief §1.6 (days on market)
    # ------------------------------------------------------------------
    list_date = fields.Date(
        help="Used together with `state='available'` and a `vacant_since` "
             "later patch to compute days-on-market.",
    )

    @api.constrains("area_sqft", "area_sqm")
    def _check_area(self):
        for unit in self:
            if unit.area_sqft and unit.area_sqm:
                if abs(unit.area_sqft * 0.092903 - unit.area_sqm) > 0.5:
                    raise ValueError(_(
                        "Unit %(name)s: area_sqft and area_sqm disagree "
                        "beyond tolerance.", name=unit.name))
