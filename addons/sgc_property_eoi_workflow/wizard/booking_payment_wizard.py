# -*- coding: utf-8 -*-
"""The booking "Record Payment" wizard.

The base wizard only ticked a flag and typed an amount, which is not proof of
payment: the money never reached Accounting, and the unit could then walk the
whole sale journey on a flag. It now also posts a real customer receipt and
registers it against the unit.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class SaleRecordPaymentWizard(models.TransientModel):
    _inherit = 'sale.record.payment.wizard'

    journal_id = fields.Many2one(
        'account.journal', string='Receipt Journal',
        default=lambda self: self._default_receipt_journal(),
        domain="[('type', 'in', ('bank', 'cash'))]",
    )
    existing_payment_id = fields.Many2one(
        'account.payment', string='Receipt Already Posted',
        domain="[('payment_type', '=', 'inbound'), ('state', 'in', ('in_process', 'paid'))]",
        help='Use a receipt that is already posted in Accounting instead of posting a new one.',
    )

    @api.model
    def _default_receipt_journal(self):
        journal = self.env['account.journal'].search([
            ('type', '=', 'bank'), ('company_id', '=', self.env.company.id)], limit=1)
        if not journal:
            journal = self.env['account.journal'].search([
                ('type', '=', 'cash'), ('company_id', '=', self.env.company.id)], limit=1)
        return journal

    def action_record(self):
        self.ensure_one()
        booking = self.booking_id
        unit = booking.property_id
        receipt = None
        if unit:
            if not booking.customer_id:
                raise UserError(_('Set the customer on the booking before recording a payment.'))
            amount = self.payment_amount
            date = self.payment_date
            journal = self.journal_id
            if self.existing_payment_id:
                amount = self.existing_payment_id.amount
                date = self.existing_payment_id.date
                journal = self.existing_payment_id.journal_id
            receipt = self.env['sgc.eoi.receipt.helper']._resolve_receipt(
                unit=unit,
                partner=booking.customer_id,
                journal=journal,
                amount=amount,
                date=date,
                memo=_('Booking %s - %s', booking.name, unit.display_name),
                existing=self.existing_payment_id,
            )
        res = super().action_record()
        if receipt:
            booking.message_post(body=_(
                'Receipt %s of %s posted in Accounting and registered against unit %s.',
                receipt.display_name, amount, unit.display_name))
        return res
