from odoo import _, fields, models
from odoo.exceptions import UserError

from ..models.property_eoi import PAYMENT_MODES


class PropertyEoiCancelWizard(models.TransientModel):
    _name = 'property.eoi.cancel.wizard'
    _description = 'Cancel / Release an EOI'

    eoi_id = fields.Many2one('property.eoi', required=True, readonly=True, ondelete='cascade')
    reason = fields.Text(string='Reason', required=True)
    paid = fields.Monetary(related='eoi_id.amount_paid', currency_field='currency_id')
    currency_id = fields.Many2one(related='eoi_id.currency_id')

    def action_confirm(self):
        self.ensure_one()
        if not (self.reason or '').strip():
            raise UserError(_('A reason is required.'))
        self.eoi_id.action_cancel(reason=self.reason.strip())
        return {'type': 'ir.actions.act_window_close'}


class PropertyEoiPaymentWizard(models.TransientModel):
    _name = 'property.eoi.payment.wizard'
    _description = 'Record an EOI payment (creates a real accounting payment)'

    eoi_id = fields.Many2one('property.eoi', required=True, readonly=True, ondelete='cascade')
    currency_id = fields.Many2one(related='eoi_id.currency_id')
    amount = fields.Monetary(required=True, currency_field='currency_id')
    date = fields.Date(default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one('account.journal', required=True, string='Journal',
                                 domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]")
    company_id = fields.Many2one(related='eoi_id.company_id')
    payment_mode = fields.Selection(PAYMENT_MODES, string='Mode of Payment', required=True, default='bank_transfer')
    reference = fields.Char(string='Cheque No. / Reference')

    def action_record(self):
        self.ensure_one()
        eoi = self.eoi_id
        if self.amount <= 0:
            raise UserError(_('The payment amount must be greater than zero.'))
        if self.journal_id.sudo().type not in ('bank', 'cash') or self.journal_id.sudo().company_id != eoi.company_id:
            raise UserError(_('Choose a bank or cash journal of the same company as the record.'))
        line = self.journal_id.sudo()._get_available_payment_method_lines('inbound')[:1]
        if not line:
            raise UserError(_('Journal %s has no inbound payment method.', self.journal_id.display_name))
        payment = self.env['account.payment'].sudo().create({
            'payment_type': 'inbound', 'partner_type': 'customer', 'partner_id': eoi.partner_id.id,
            'amount': self.amount, 'currency_id': eoi.currency_id.id, 'date': self.date,
            'journal_id': self.journal_id.id, 'payment_method_line_id': line.id,
            'memo': _('EOI %s', eoi.name), 'company_id': eoi.company_id.id,
        })
        payment.action_post()
        eoi.sudo().write({'payment_ids': [(4, payment.id)], 'payment_mode': self.payment_mode,
                   'payment_reference': self.reference or eoi.payment_reference})
        eoi.message_post(body=_('Payment %(pay)s of %(amt)s recorded (%(mode)s).', pay=payment.display_name,
                                amt=self.amount, mode=dict(PAYMENT_MODES).get(self.payment_mode)))
        return {'type': 'ir.actions.act_window_close'}


class PropertySaleCancelWizard(models.TransientModel):
    _name = 'property.sale.cancel.wizard'
    _description = 'Cancel a Confirmed Sale'

    booking_id = fields.Many2one('property.vendor', required=True, readonly=True, ondelete='cascade')
    reason = fields.Text(required=True)
    paid = fields.Monetary(related='booking_id.booking_paid_amount', currency_field='currency_id')
    currency_id = fields.Many2one(related='booking_id.currency_id')

    def action_confirm(self):
        self.ensure_one()
        self.booking_id._sgc_cancel_confirmed_sale(self.reason)
        return {'type': 'ir.actions.act_window_close'}
