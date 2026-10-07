# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template (reconciled build, 2026-08-31).
#
# Brief §2.16 — answers "average time spent per transaction on
# DLD/Trakheesi compliance, Ejari registration, and NOC acquisition."
# Records the per-event open/close timestamps so averages are
# computable over time.
#
# Constraint #4 model name: `sgc.compliance.event`.
from odoo import _, api, fields, models


class SgcComplianceEvent(models.Model):
    _name = "sgc.compliance.event"
    _description = "Compliance event timeline (DLD / Trakheesi / Ejari / NOC)"
    _order = "opened_at desc, sequence, id"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _rec_name = "display_name"

    tenant_id = fields.Many2one(
        "sgc.brokerage.tenant", required=True, check_company=True,
    )
    sequence = fields.Integer(default=10)
    event_type = fields.Selection(
        selection=[
            ("dld", "DLD"),
            ("trakheesi", "Trakheesi"),
            ("ejari", "Ejari"),
            ("noc", "NOC"),
            ("rera_form_a", "RERA Form A"),
            ("rera_form_b", "RERA Form B"),
            ("rera_form_i", "RERA Form I"),
            ("kyc_submission", "KYC submission"),
            ("aml_alert", "AML alert"),
            ("other", "Other"),
        ],
        required=True, index=True,
    )
    transaction_ref = fields.Char(
        index=True,
        help="Free-text cross-reference to the originating sale-order, "
             "tenancy contract, or property.unit record.",
    )
    counterparty_id = fields.Many2one(
        "res.partner",
        help="Optional — the buyer/tenant counterparty for this event.",
    )
    unit_id = fields.Many2one(
        "re.unit",
        domain="[('tenant_id', '=', tenant_id)]",
        help="Optional — the unit/property record this event relates to.",
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        help="Linked document evidence; uses the polymorphic res_model/"
             "res_id pair (no separate vault model per Constraint #6).",
    )
    opened_at = fields.Datetime(
        required=True, default=fields.Datetime.now, index=True,
    )
    closed_at = fields.Datetime(index=True)
    duration_hours = fields.Float(
        compute="_compute_duration_hours", store=True, readonly=True,
        help="Closed-at minus opened-at, in hours. Computed via "
             "Odoo's standard compute API so it re-evaluates when "
             "either timestamp changes.",
    )
    outcome = fields.Selection(
        selection=[
            ("open", "Open"),
            ("closed_ok", "Closed — OK"),
            ("closed_failed", "Closed — Failed"),
            ("closed_cancelled", "Closed — Cancelled"),
        ],
        default="open", required=True, index=True,
    )
    notes = fields.Text()

    display_name = fields.Char(
        compute="_compute_display_name", store=True, readonly=True,
    )

    _sgc_compliance_event_opened_required = models.Constraint(
        "CHECK(opened_at IS NOT NULL)",
        "Every compliance event must have an open timestamp.",
    )

    @api.depends("event_type", "opened_at", "transaction_ref")
    def _compute_display_name(self):
        LABELS = dict(self._fields["event_type"].selection)
        for ev in self:
            ev.display_name = "{} @ {} ({})".format(
                LABELS.get(ev.event_type, ev.event_type),
                ev.opened_at or "",
                ev.transaction_ref or "no-ref",
            )

    @api.depends("opened_at", "closed_at")
    def _compute_duration_hours(self):
        for ev in self:
            if ev.opened_at and ev.closed_at:
                delta = ev.closed_at - ev.opened_at
                ev.duration_hours = round(
                    delta.total_seconds() / 3600.0, 2)
            else:
                ev.duration_hours = 0.0
