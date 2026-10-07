# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template (reconciled build, 2026-08-31).
#
# Brief §2.17 — answers "top 3-5 recurring failure points in
# brokerage and in property-management operations." Captures per-
# tenant incidents with a category taxonomy so recurring failures
# are observable.
#
# Constraint #4 model name: `sgc.brokerage.incident`.
#
# Note: the data-extraction report's §2.33 (founder pain point) maps
# to incidents where `category='founder_pain'`. `sgc.brokerage.tenant.
# founder_pain_point_log_ids` is a relational view into this table.
from odoo import _, api, fields, models


class SgcBrokerageIncident(models.Model):
    _name = "sgc.brokerage.incident"
    _description = "Brokerage / PM failure-point incident log"
    _order = "last_seen_at desc, sequence, id"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "summary"

    tenant_id = fields.Many2one(
        "sgc.brokerage.tenant",
        required=True, check_company=True, tracking=True,
    )
    sequence = fields.Integer(default=10)
    summary = fields.Char(required=True, index=True)
    category = fields.Selection(
        selection=[
            ("lead_lost", "Lead lost"),
            ("commission_mismatch", "Commission mismatch"),
            ("compliance_delay", "Compliance delay"),
            ("amli_kyc_failure", "AML / KYC failure"),
            ("uaedds_bounce", "UAEDDS bounce"),
            ("cheque_bounce", "Cheque bounce"),
            ("portal_sync", "Portal sync (Bayut / Property Finder)"),
            ("handover_failure", "Handover failure"),
            ("maintenance_sla_breach", "Maintenance SLA breach"),
            ("data_quality", "Data quality"),
            ("integration_outage", "Integration outage"),
            ("founder_pain", "Founder pain (Brief §2.33)"),
            ("other", "Other"),
        ],
        required=True, index=True, tracking=True,
    )
    severity = fields.Selection(
        selection=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("critical", "Critical"),
        ],
        default="medium", required=True, index=True,
    )
    root_cause = fields.Text()
    recurrence_count = fields.Integer(
        default=1,
        help="Number of times this incident's category has occurred "
             "in the rolling 90-day window.",
    )
    last_seen_at = fields.Datetime(
        default=fields.Datetime.now, required=True, index=True,
    )
    first_seen_at = fields.Datetime(
        default=fields.Datetime.now, required=True,
    )
    resolved_at = fields.Datetime()
    is_resolved = fields.Boolean(
        compute="_compute_is_resolved", store=True, readonly=True,
    )

    _sgc_brokerage_incident_chronicler = models.Constraint(
        "CHECK(recurrence_count >= 1)",
        "recurrence_count must be >= 1.",
    )

    @api.depends("resolved_at")
    def _compute_is_resolved(self):
        for inc in self:
            inc.is_resolved = bool(inc.resolved_at)
