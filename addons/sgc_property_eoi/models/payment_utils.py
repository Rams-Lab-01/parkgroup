"""Shared helpers: which accounting payments count as "received" for an EOI / booking."""

from odoo import api, fields, models

PARAM_VERIFIED_STATES = 'sgc_eoi.payment_verified_states'
DEFAULT_VERIFIED_STATES = ('in_process', 'paid')
EPS = 0.005


class SgcPaymentHelper(models.AbstractModel):
    _name = 'sgc.payment.helper'
    _description = 'EOI / booking payment helper'

    @api.model
    def _verified_states(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_VERIFIED_STATES) or ''
        states = tuple(s.strip() for s in raw.split(',') if s.strip())
        return states or DEFAULT_VERIFIED_STATES

    @api.model
    def _counted_amount(self, payments, currency, company):
        """Sum of the posted, inbound customer payments, expressed in `currency`.

        A payment counts only when it is really posted (state in `sgc_eoi.payment_verified_states`, default
        in_process + paid) - draft, cancelled and rejected payments never count."""
        states = self._verified_states()
        total = 0.0
        for pay in payments.sudo():
            if pay.state not in states or pay.payment_type != 'inbound':
                continue
            total += pay.currency_id._convert(
                pay.amount, currency, company, pay.date or fields.Date.context_today(self))
        return total

    @api.model
    def _counted_payments(self, payments):
        states = self._verified_states()
        return payments.sudo().filtered(lambda p: p.state in states and p.payment_type == 'inbound')
