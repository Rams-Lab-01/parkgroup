# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template.
from odoo import _, api, fields, models


class SgcBrokerageKit(models.Model):
    """Curated bundle of audit-cleared real-estate modules.

    A *kit* is the canonical way to express the real-estate brokerage + ERP
    rollout for a vertical scope. Each kit has a static list of recommended
    addons (one row per module name) and a recommended ``depends`` ordering
    for a Docker-compose build.

    The kit object is **declarative**: code does not consume kits at
    runtime. Instead, the ``docs/REAL_ESTATE_BROKERAGE_ROLLOUT.md``
    playbook uses kits as the *menu-of-options* for each rollout phase,
    and the audit lint tool uses them as a reference for the canonical
    per-vertical addon-path.
    """

    _name = "sgc.brokerage.kit"
    _description = "Real-estate brokerage kit (curated addon bundle)"
    _order = "sequence, name"

    name = fields.Char(required=True, index=True)
    code = fields.Char(required=True, index=True, copy=False)
    sequence = fields.Integer(default=10)
    vertical = fields.Selection(
        [
            ("brokerage", "Brokerage (default)"),
            ("developer", "Developer (off-plan property)"),
            ("offplan_rental", "Offplan + Rental"),
            ("construction", "Construction-management vertical"),
            ("growth", "Growth / broker portal"),
        ],
        required=True,
    )
    description = fields.Html()
    addon_line_ids = fields.One2many(
        "sgc.brokerage.kit.line", "kit_id", string="Module bundle",
    )
    doc_url = fields.Char(
        help="Pointer to the rollout playbook section this kit feeds.",
    )

    _sgc_brokerage_kit_code_unique = models.Constraint(
        "unique(code)", "Kit code must be unique.",
    )


class SgcBrokerageKitLine(models.Model):
    _name = "sgc.brokerage.kit.line"
    _description = "Line in a real-estate brokerage kit"
    _order = "sequence, addon"

    kit_id = fields.Many2one(
        "sgc.brokerage.kit", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    addon = fields.Char(
        required=True, index=True,
        help="Odoo addon technical name. Must match an addon that exists "
             "in the addon path; the audit lint tool validates this.",
    )
    purpose = fields.Selection(
        [
            ("foundation", "Foundation (always install)"),
            ("vertical", "Vertical (install for this kit only)"),
            ("growth", "Growth (brokers / portal / marketing)"),
            ("compliance", "Compliance (AML / KYC)"),
            ("reporting", "Reporting (financial / executive)"),
            ("erp_hr", "ERP — HR / payroll"),
        ],
        required=True,
    )
    rollover_note = fields.Char(
        help="Free-text — what the integrator must verify before enabling "
             "this addon in a tenant. Drawn from the audit's blocker "
             "inventory where applicable.",
    )
    quarantined = fields.Boolean(
        default=False, readonly=True,
        help="True if the addon is held (see 30_QUARANTINE/). Kits may "
             "include quarantined modules only with an explicit founder "
             "sign-off and the resolution-path complete.",
    )
