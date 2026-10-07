# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from odoo import api, fields, models, _


class CrmLead(models.Model):
    """CRM lead/opportunity — the single spine of the property-sale journey.

    Adds the contract smart buttons and, crucially, the *reverse* linkage to the
    property-management sale instruments (EOI / booking / SPA) that previously
    never pointed back at the lead.
    """
    _inherit = "crm.lead"

    # ── The property sale instruments, viewed from the lead ──────────────
    contract_ids = fields.One2many(
        "sale.contract", "lead_id", string="Sale Contracts")
    eoi_contract_ids = fields.One2many(
        "sale.contract", "lead_id", string="EOI / Reservations",
        domain=[("state", "=", "eoi")])
    booking_contract_ids = fields.One2many(
        "sale.contract", "lead_id", string="Bookings",
        domain=[("state", "in", ("booked", "confirmed", "spa_issued"))])
    signed_contract_ids = fields.One2many(
        "sale.contract", "lead_id", string="Signed SPAs",
        domain=[("state", "in", ("spa_signed", "signed", "completed"))])

    contract_count = fields.Integer(
        string="Contracts", compute="_compute_contract_counts")
    eoi_count = fields.Integer(
        string="EOIs", compute="_compute_contract_counts")
    booking_count = fields.Integer(
        string="Bookings", compute="_compute_contract_counts")
    signed_count = fields.Integer(
        string="Signed SPAs", compute="_compute_contract_counts")

    # ── Journey SLA / internal control ───────────────────────────────────
    journey_days_in_stage = fields.Integer(
        string="Days in Stage", compute="_compute_journey_days_in_stage",
        help="Days since this lead last changed stage. Used by the pipeline "
             "SLA monitor to surface stalled deals.")

    # ─────────────────────────────────────────────────────────────────────
    # Computes
    # ─────────────────────────────────────────────────────────────────────
    @api.depends("contract_ids.state")
    def _compute_contract_counts(self):
        for lead in self:
            contracts = lead.contract_ids
            lead.contract_count = len(contracts)
            lead.eoi_count = len(contracts.filtered(lambda c: c.state == "eoi"))
            lead.booking_count = len(contracts.filtered(
                lambda c: c.state in ("booked", "confirmed", "spa_issued")))
            lead.signed_count = len(contracts.filtered(
                lambda c: c.state in ("spa_signed", "signed", "completed")))

    @api.depends("date_last_stage_update")
    def _compute_journey_days_in_stage(self):
        today = fields.Date.context_today(self)
        for lead in self:
            stamp = lead.date_last_stage_update
            lead.journey_days_in_stage = (
                (today - stamp.date()).days if stamp else 0)

    # ─────────────────────────────────────────────────────────────────────
    # Portable stage resolution (no hardcoded ids — same contract as the
    # dashboard resolver, so it survives any tenant's stage numbering).
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def _journey_stage(self, *names):
        Stage = self.env["crm.stage"]
        for name in names:
            stage = Stage.search([("name", "=", name)], limit=1)
            if stage:
                return stage
        return Stage.browse()

    # ─────────────────────────────────────────────────────────────────────
    # Smart-button actions
    # ─────────────────────────────────────────────────────────────────────
    def _contract_action(self, name, domain):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": "sale.contract",
            "view_mode": "list,form",
            "domain": [("lead_id", "=", self.id)] + list(domain),
            "context": {
                "default_lead_id": self.id,
                "default_property_id": self.property_id.id or False,
                "default_buyer_id": self.partner_id.id or False,
                "search_default_group_by_state": 1,
            },
            "target": "current",
        }

    def action_view_contracts(self):
        return self._contract_action(_("Sale Contracts"), [])

    def action_view_eoi_contracts(self):
        return self._contract_action(
            _("EOI / Reservations"), [("state", "=", "eoi")])

    def action_view_booking_contracts(self):
        return self._contract_action(
            _("Bookings"), [("state", "in", ("booked", "confirmed", "spa_issued"))])

    def action_view_signed_contracts(self):
        return self._contract_action(
            _("Signed SPAs"), [("state", "in", ("spa_signed", "signed", "completed"))])

    # ─────────────────────────────────────────────────────────────────────
    # Journey launch points (carry the lead into the EOI/booking wizard)
    # ─────────────────────────────────────────────────────────────────────
    def action_register_eoi(self):
        """Open the EOI wizard pre-filled with this lead's property/buyer and
        carrying the lead so the created contract links straight back."""
        self.ensure_one()
        if not self.property_id:
            from odoo.exceptions import UserError
            raise UserError(_(
                "Set the Property on this lead before registering an EOI."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Register Expression of Interest (EOI)"),
            "res_model": "eoi.registration.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_lead_id": self.id,
                "default_property_id": self.property_id.id,
                "default_buyer_id": self.partner_id.id or False,
                "default_sale_price":
                    self.property_id.sale_price or self.property_id.price or 0.0,
            },
        }

    @api.model
    def _cron_flag_stalled_leads(self):
        """SLA monitor (internal control): schedule a to-do on the owner of
        every open opportunity whose stage hasn't moved for N days
        (``ir.config_parameter`` ``sgc_lead_journey.sla_days``, default 14).
        Idempotent — a lead that already has an open activity is left alone,
        and the flag always leaves a visible activity/chatter trace."""
        from datetime import datetime, timedelta
        days = int(self.env["ir.config_parameter"].sudo().get_param(
            "sgc_lead_journey.sla_days", "14") or 14)
        cutoff = fields.Datetime.to_string(datetime.now() - timedelta(days=days))
        leads = self.search([
            ("active", "=", True),
            ("type", "=", "opportunity"),
            ("date_last_stage_update", "!=", False),
            ("date_last_stage_update", "<=", cutoff),
            ("probability", ">", 0),
            ("probability", "<", 100),
        ])
        activity_type = self.env.ref(
            "mail.mail_activity_data_todo", raise_if_not_found=False)
        flagged = 0
        for lead in leads:
            if any(not act.date_done for act in lead.activity_ids):
                continue
            summary = _("SLA breach: stalled > %s days") % days
            if activity_type:
                lead.activity_schedule(
                    activity_type_id=activity_type.id,
                    summary=summary,
                    user_id=lead.user_id.id or self.env.uid,
                    note=_("Auto-flagged by the property lead journey SLA monitor."),
                )
            else:
                lead.message_post(body=summary)
            flagged += 1
        return flagged

    def action_convert_to_booking(self):
        """Open the EOI→Booking wizard pre-filled from this lead."""
        self.ensure_one()
        if not self.property_id:
            from odoo.exceptions import UserError
            raise UserError(_(
                "Set the Property on this lead before creating a booking."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Convert to Booking"),
            "res_model": "eoi.to.booking.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_lead_id": self.id,
                "default_property_id": self.property_id.id,
                "default_buyer_id": self.partner_id.id or False,
                "default_sale_price":
                    self.property_id.sale_price or self.property_id.price or 0.0,
            },
        }
