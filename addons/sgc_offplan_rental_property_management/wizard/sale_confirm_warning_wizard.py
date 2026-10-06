# -*- coding: utf-8 -*-
# Wizard: Record Payment for a booking
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.sgc_offplan_rental_property_management.services import (
    sgc_audit_internal_service,
)


class SaleRecordPaymentWizard(models.TransientModel):
    _name = 'sale.record.payment.wizard'
    _description = 'Record Payment for Booking'

    booking_id = fields.Many2one('property.vendor', string='Booking', required=True,
                                  readonly=True)
    payment_amount = fields.Monetary(string='Payment Amount', currency_field='currency_id',
                                      required=True)
    payment_date = fields.Date(string='Payment Date', default=lambda self: fields.Date.today(),
                                required=True)
    currency_id = fields.Many2one('res.currency', string='Currency',
                                   default=lambda self: self.env.company.currency_id,
                                   readonly=True)

    def action_record(self):
        self.ensure_one()
        if self.payment_amount <= 0:
            raise UserError(_('Payment amount must be greater than zero.'))
        self.booking_id.write({
            'payment_recorded': True,
            'payment_amount': self.payment_amount,
            'payment_date': self.payment_date,
        })
        # Semantic audit event, through the same service the booking-side
        # transitions use. There is no _log_critical_audit_event method on
        # property.vendor or on the critical audit mixin; the previous call
        # raised AttributeError, so this button failed on every invocation.
        service = sgc_audit_internal_service.SgcAuditInternalService(self.env)
        service.capture_event(
            tier='2',
            operation='payment_recorded',
            operation_label='Payment Recorded',
            model='property.vendor',
            res_id=self.booking_id.id,
            res_display_name=self.booking_id.name,
            reason='Payment of %s recorded on %s' % (
                self.payment_amount, self.payment_date),
            source='ui',
            observed_fields=False,
        )
        return {'type': 'ir.actions.act_window_close'}


class SaleConfirmWarningWizard(models.TransientModel):
    _name = 'sale.confirm.warning.wizard'
    _description = 'Confirm Sale Warning (Permissive Mode)'

    booking_id = fields.Many2one('property.vendor', string='Booking', required=True,
                                  readonly=True)
    warning_message = fields.Text(string='Warning', default='', readonly=True)
    acknowledgement_text = fields.Text(string='Acknowledgement', required=True,
                                       help='Acknowledge that you are confirming sale without recorded payment.')

    def action_confirm_with_acknowledgement(self):
        self.ensure_one()
        if not self.acknowledgement_text or len(self.acknowledgement_text.strip()) < 10:
            raise UserError(_('Please provide a meaningful acknowledgement (at least 10 characters).'))
        return self.booking_id.action_confirm_sale(acknowledgement=self.acknowledgement_text)
