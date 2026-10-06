from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.property_vendor import _audit


class SaleRecordPaymentWizard(models.TransientModel):
    """Extends the base "Record Payment": it used to tick a flag and store a typed amount. It now posts a REAL
    customer payment in Accounting, links it to the booking, and lets the verified amount drive the sales gate."""
    _inherit = 'sale.record.payment.wizard'

    journal_id = fields.Many2one('account.journal', string='Journal', required=True,
                                 domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    company_id = fields.Many2one(related='booking_id.company_id')
    payment_method_line_id = fields.Many2one(
        'account.payment.method.line', string='Payment Method',
        domain="[('journal_id', '=', journal_id), ('payment_type', '=', 'inbound')]")

    def action_record(self):
        self.ensure_one()
        booking = self.booking_id
        if self.payment_amount <= 0:
            raise UserError(_('Payment amount must be greater than zero.'))
        if not booking.customer_id:
            raise UserError(_('Set the customer on the booking before recording a payment.'))
        if booking.booking_amount and self.payment_amount - booking.booking_outstanding > 0.005 \
                and booking.booking_outstanding:
            raise UserError(_('The payment (%(pay)s) is more than the outstanding booking amount (%(left)s).',
                              pay=self.payment_amount, left=booking.booking_outstanding))
        if self.journal_id.sudo().type not in ('bank', 'cash') or self.journal_id.sudo().company_id != booking.company_id:
            raise UserError(_('Choose a bank or cash journal of the same company as the record.'))
        line = self.payment_method_line_id or self.journal_id.sudo()._get_available_payment_method_lines('inbound')[:1]
        if not line:
            raise UserError(_('Journal %s has no inbound payment method.', self.journal_id.display_name))
        payment = self.env['account.payment'].sudo().create({
            'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': booking.customer_id.id,
            'amount': self.payment_amount, 'currency_id': booking.currency_id.id, 'date': self.payment_date,
            'journal_id': self.journal_id.id, 'payment_method_line_id': line.id,
            'memo': _('Booking %s', booking.name), 'company_id': booking.company_id.id,
        })
        payment.action_post()
        booking.sudo().write({'payment_ids': [(4, payment.id)]})
        booking._sgc_sync_payment_flags()
        _audit(self.env, tier='2', operation='payment_recorded', operation_label='Payment Recorded',
               model='property.vendor', res_id=booking.id, res_display_name=booking.name,
               reason='Payment %s of %s recorded on %s (accounting payment %s)' % (
                   self.payment_amount, self.payment_amount, self.payment_date, payment.display_name),
               source='ui', observed_fields=False)
        booking.message_post(body=_('Payment %(pay)s recorded: %(amt)s. Paid %(paid)s of %(due)s.',
                                    pay=payment.display_name, amt=self.payment_amount, paid=booking.booking_paid_amount,
                                    due=booking.booking_amount))
        return {'type': 'ir.actions.act_window_close'}
