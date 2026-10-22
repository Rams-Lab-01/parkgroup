# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class EoiToBookingWizard(models.TransientModel):
    _name = 'eoi.to.booking.wizard'
    _description = 'Convert EOI to Formal Booking'

    contract_id = fields.Many2one('sale.contract', string='Contract / EOI Record')
    property_id = fields.Many2one('property.details', string='Property', required=True)
    buyer_id = fields.Many2one('res.partner', string='Purchaser', required=True)
    sale_price = fields.Monetary(string='Sale Price', currency_field='currency_id', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    booking_amount = fields.Monetary(
        string='Booking Deposit Amount (AED)',
        currency_field='currency_id',
        required=True,
        help='Deposit required to convert EOI to confirmed booking reservation.',
    )
    payment_schedule_id = fields.Many2one(
        'payment.schedule', string='Payment Schedule Plan',
        domain=[('schedule_type', '=', 'sale')],
    )
    booking_date = fields.Date(string='Booking Date', default=fields.Date.context_today, required=True)

    # ------------------------------------------------------------------
    # The booking receipt
    # ------------------------------------------------------------------
    record_booking_receipt = fields.Boolean(
        string='Post the booking deposit receipt now',
        default=False,
        help='Tick when the booking deposit is a NEW payment. Leave it off when the money '
             'already received (the EOI receipt) is what carries the booking.',
    )
    payment_amount = fields.Monetary(
        string='Amount Received', currency_field='currency_id',
        default=0.0,
        help='The amount actually received, posted as a customer receipt in Accounting.',
    )
    payment_date = fields.Date(string='Receipt Date', default=fields.Date.context_today, required=True)
    journal_id = fields.Many2one(
        'account.journal', string='Receipt Journal',
        default=lambda self: self._default_journal(),
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    existing_payment_id = fields.Many2one(
        'account.payment', string='Receipt Already Posted',
        domain="[('payment_type', '=', 'inbound'), ('state', 'in', ('in_process', 'paid'))]",
        help='Use a receipt that is already posted in Accounting instead of posting a new one.',
    )
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    @api.model
    def _default_journal(self):
        journal = self.env['account.journal'].search([
            ('type', '=', 'bank'), ('company_id', '=', self.env.company.id)], limit=1)
        if not journal:
            journal = self.env['account.journal'].search([
                ('type', '=', 'cash'), ('company_id', '=', self.env.company.id)], limit=1)
        return journal

    @api.onchange('property_id')
    def _onchange_property_id(self):
        if self.property_id:
            self.sale_price = self.property_id.sale_price or self.property_id.price or 0.0
            self.booking_amount = (self.sale_price * 0.10)
            eoi_active = self.property_id.sale_contract_ids.filtered(lambda c: c.state == 'eoi')
            if eoi_active:
                self.contract_id = eoi_active[0].id
                self.buyer_id = eoi_active[0].buyer_id.id
            # Nothing received yet? Then this booking has to bring its own receipt.
            self.record_booking_receipt = not self.property_id._sgc_eoi_receipts()

    @api.onchange('booking_amount')
    def _onchange_booking_amount(self):
        if self.record_booking_receipt:
            self.payment_amount = self.booking_amount

    @api.onchange('existing_payment_id')
    def _onchange_existing_payment_id(self):
        if self.existing_payment_id:
            self.payment_amount = self.existing_payment_id.amount
            self.payment_date = self.existing_payment_id.date

    def action_convert_to_booked(self):
        self.ensure_one()
        contract = self.contract_id
        if not contract and self.property_id:
            eoi_active = self.property_id.sale_contract_ids.filtered(lambda c: c.state == 'eoi')
            if eoi_active:
                contract = eoi_active[0]

        # The money gate: a unit may only be booked when a receipt is registered
        # against it in Accounting.
        receipts = self.property_id._sgc_eoi_receipts()
        new_receipt = None
        if self.record_booking_receipt or self.existing_payment_id:
            new_receipt = self._resolve_receipt()
        if not receipts and not new_receipt:
            raise UserError(_(
                'No posted receipt is registered against unit %s. Record the booking deposit '
                'in Accounting against the unit (or tick "Post the booking deposit receipt '
                'now") before booking it.', self.property_id.display_name))

        if contract:
            contract.write({
                'state': 'booked',
                'booking_amount': self.booking_amount,
                'booking_date': self.booking_date,
                'payment_schedule_id': self.payment_schedule_id.id if self.payment_schedule_id else contract.payment_schedule_id.id,
            })
            if new_receipt:
                contract.write({'eoi_payment_ids': [(4, new_receipt.id)]})
            self.property_id.write({'state': 'booked'})
            return {
                'name': _('Sale Contract - Booked'),
                'type': 'ir.actions.act_window',
                'res_model': 'sale.contract',
                'res_id': contract.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            # Create direct booking
            vals = {
                'property_id': self.property_id.id,
                'buyer_id': self.buyer_id.id,
                'seller_id': self.property_id.owner_id.id if self.property_id.owner_id else False,
                'sale_price': self.sale_price,
                'currency_id': self.currency_id.id,
                'booking_amount': self.booking_amount,
                'booking_date': self.booking_date,
                'payment_schedule_id': self.payment_schedule_id.id if self.payment_schedule_id else False,
                'state': 'booked',
                'company_id': self.env.company.id,
            }
            new_contract = self.env['sale.contract'].create(vals)
            if new_receipt:
                new_contract.write({'eoi_payment_ids': [(4, new_receipt.id)]})
            self.property_id.write({'state': 'booked'})
            return {
                'name': _('Sale Contract - Booked'),
                'type': 'ir.actions.act_window',
                'res_model': 'sale.contract',
                'res_id': new_contract.id,
                'view_mode': 'form',
                'target': 'current',
            }

    def _resolve_receipt(self):
        """The posted booking receipt, registered against the unit."""
        self.ensure_one()
        memo = _('Booking deposit %s - %s', self.property_id.display_name, self.buyer_id.name)
        amount, date, journal = self.payment_amount, self.payment_date, self.journal_id
        if self.existing_payment_id:
            amount = self.existing_payment_id.amount
            date = self.existing_payment_id.date
            journal = self.existing_payment_id.journal_id
        return self.env['sgc.eoi.receipt.helper']._resolve_receipt(
            unit=self.property_id,
            partner=self.buyer_id,
            journal=journal,
            amount=amount,
            date=date,
            memo=memo,
            existing=self.existing_payment_id,
        )
