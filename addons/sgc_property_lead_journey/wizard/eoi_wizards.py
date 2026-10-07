# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from odoo import fields, models


class EoiRegistrationWizard(models.TransientModel):
    _inherit = "eoi.registration.wizard"

    lead_id = fields.Many2one(
        "crm.lead", string="Lead / Opportunity",
        help="Originating CRM lead. Carried through to the created EOI so the "
             "deal is never orphaned from the pipeline.")

    def action_register_eoi(self):
        res = super().action_register_eoi()
        if self.lead_id and res.get("res_id"):
            contract = self.env["sale.contract"].browse(res["res_id"])
            contract.lead_id = self.lead_id
        return res


class EoiToBookingWizard(models.TransientModel):
    _inherit = "eoi.to.booking.wizard"

    lead_id = fields.Many2one(
        "crm.lead", string="Lead / Opportunity",
        help="Originating CRM lead. Carried through to the booking/contract.")

    def action_convert_to_booked(self):
        res = super().action_convert_to_booked()
        if self.lead_id and res.get("res_id"):
            contract = self.env["sale.contract"].browse(res["res_id"])
            if not contract.lead_id:
                contract.lead_id = self.lead_id
        return res
