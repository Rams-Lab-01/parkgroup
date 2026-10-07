# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template (reconciled build, 2026-08-31).
#
# Brief §6.29 — answers "which of the seven platform layers
# (Predictive Signal Engine, AI Avatar Qualification, Trust Passport,
# Co-Brokerage Settlement Network, Portfolio Wealth Dashboard, Market
# Intelligence Product, Instant Liquidity / iBuyer) resonates most
# strongly with the long-term vision." Captures the brokerage's
# priority ordering per tenant.
#
# Constraint #4 model name: `sgc.strategy.layer_priority`.
from odoo import _, api, fields, models


class SgcStrategyLayerPriority(models.Model):
    _name = "sgc.strategy.layer_priority"
    _description = "Per-tenant priority ordering of the seven platform layers"
    _order = "tenant_id, priority"
    _rec_name = "display_name"

    tenant_id = fields.Many2one(
        "sgc.brokerage.tenant", required=True, check_company=True,
    )
    layer_id = fields.Selection(
        selection=[
            ("predictive_signal", "Predictive Signal Engine"),
            ("ai_avatar", "AI Avatar Qualification"),
            ("trust_passport", "Trust Passport"),
            ("co_brokerage_network", "Co-Brokerage Settlement Network"),
            ("portfolio_wealth", "Portfolio Wealth Dashboard"),
            ("market_intel", "Market Intelligence Product"),
            ("instant_liquidity", "Instant Liquidity / iBuyer"),
        ],
        required=True, index=True,
        help="One of the seven platform layers catalogued in Brief §6.29 "
             "and the data-extraction report.",
    )
    priority = fields.Integer(
        required=True,
        help="1 (most strongly resonates) through 7 (lowest priority). "
             "Computed server-side to enforce uniqueness per tenant.",
    )
    target_phase = fields.Integer(
        help="Phase at which the brokerage aims to deliver this layer. "
             "Maps to `docs/REAL_ESTATE_BROKERAGE_ROLLOUT.md` phases "
             "0-8. For layers targeted beyond Phase 8 (post-rollout), "
             "the value should be 9+.",
    )
    rationale = fields.Text()

    display_name = fields.Char(
        compute="_compute_display_name", store=True, readonly=True,
    )

    _sgc_strategy_layer_unique_per_tenant = models.Constraint(
        "unique(tenant_id, layer_id)",
        "Each layer appears at most once per tenant.",
    )
    _sgc_strategy_priority_unique_per_tenant = models.Constraint(
        "unique(tenant_id, priority)",
        "Each priority value (1-7) appears at most once per tenant.",
    )

    @api.depends("layer_id", "priority")
    def _compute_display_name(self):
        LABELS = dict(self._fields["layer_id"].selection)
        for row in self:
            row.display_name = "{}. {}".format(
                row.priority, LABELS.get(row.layer_id, row.layer_id or "")
            )
