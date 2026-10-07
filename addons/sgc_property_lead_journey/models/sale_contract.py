# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from odoo import api, fields, models, _


class SaleContract(models.Model):
    """Attach the property-sale instrument to the CRM lead spine.

    ``sale.contract`` is the real property-sale document (EOI -> booked ->
    confirmed -> SPA). Until now nothing pointed it back at the originating
    ``crm.lead``, so the CRM pipeline and the sale pipeline were disjoint. This
    adds the link and drives the lead's stage automatically as the contract
    advances.
    """
    _inherit = "sale.contract"

    lead_id = fields.Many2one(
        "crm.lead", string="Lead / Opportunity",
        index=True, ondelete="set null", tracking=True,
        help="The CRM lead/opportunity this property sale instrument fulfils.")
    lead_source_id = fields.Many2one(
        related="lead_id.source_id", string="Lead Source", store=False)

    # Contract states that mean "the deal is won" (SPA signed) vs "dead".
    _JOURNEY_WON_STATES = ("spa_signed", "signed", "completed")
    _JOURNEY_DEAD_STATES = ("refunded", "cancelled")

    # ─────────────────────────────────────────────────────────────────────
    # Keep the lead's stage in lock-step with the contract state
    # ─────────────────────────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        contracts = super().create(vals_list)
        contracts._sync_lead_stage()
        return contracts

    def write(self, vals):
        res = super().write(vals)
        if "state" in vals or "lead_id" in vals:
            self._sync_lead_stage()
        return res

    def _sync_lead_stage(self):
        """Advance (or re-open) the linked lead's stage to match the contract.

        Best practice: the sale document is the system of record for deal
        progress, so the CRM stage is *derived* from it — reps never have to
        remember to move the lead by hand, and the dashboard/pipeline can never
        disagree with the contract list.
        """
        Lead = self.env["crm.lead"]
        won = Lead._journey_stage("Won")
        in_progress = Lead._journey_stage("Proposition", "Proposal", "Qualified")
        for contract in self:
            lead = contract.lead_id
            if not lead:
                continue
            if contract.state in self._JOURNEY_WON_STATES:
                vals = {"probability": 100}
                if won:
                    vals["stage_id"] = won.id
                lead.write(vals)
            elif contract.state in self._JOURNEY_DEAD_STATES:
                # EOI refunded / contract cancelled — the deal is back on the
                # market; re-open the lead for re-engagement rather than
                # silently leaving it parked in a won-looking stage.
                if in_progress:
                    lead.write({"stage_id": in_progress.id})
            elif contract.state in ("eoi", "booked", "confirmed", "spa_issued"):
                # Actively in the sale funnel -> advance the lead to the
                # proposal stage (EOI/booking are strong buying signals).
                if in_progress:
                    lead.write({"stage_id": in_progress.id})
