# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class EoiRegistrationWizard(models.TransientModel):
    _name = 'eoi.registration.wizard'
    _description = 'Register Expression of Interest (EOI)'

    property_id = fields.Many2one('property.details', string='Property', required=True)
    buyer_id = fields.Many2one('res.partner', string='Purchaser', required=True)
    joint_buyer_id = fields.Many2one('res.partner', string='Joint Purchaser')
    sale_price = fields.Monetary(string='Sale Price', currency_field='currency_id', required=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    eoi_amount = fields.Monetary(
        string='EOI Deposit (AED)',
        currency_field='currency_id',
        default=50000.0,
        required=True,
        help='Refundable initial deposit for pre-launch / pre-booking reservation.',
    )
    eoi_payment_mode = fields.Selection([
        ('cheque', 'Current Dated Cheque'),
        ('post_dated_cheque', 'Post-Dated Cheque (PDC)'),
        ('card', 'Credit / Debit Card'),
        ('bank_transfer', 'Bank Wire Transfer'),
        ('card_auth', 'Card Authorization Letter'),
        ('cash', 'Cash'),
    ], string='Mode of Payment', default='cheque', required=True)
    eoi_cheque_no = fields.Char(string='Cheque / Auth Ref')
    eoi_cheque_bank = fields.Char(string='Drawee Bank Name', default='UAE Licensed Bank')
    eoi_cheque_date = fields.Date(string='Cheque Date / PDC Maturity')
    eoi_date = fields.Date(string='EOI Date', default=fields.Date.context_today, required=True)
    eoi_expiry_date = fields.Date(string='Launch / Validity Date')
    notes = fields.Text(
        string='Special Conditions / Remarks',
        default='AED 50,000 (CHEQUE) - Fully refundable within 7 days from the booking date. CHQ not to be cashed in.',
    )

    # ------------------------------------------------------------------
    # The receipt: the EOI money has to exist in Accounting
    # ------------------------------------------------------------------
    payment_amount = fields.Monetary(
        string='Amount Received', currency_field='currency_id',
        default=50000.0, required=True,
        help='The amount actually received. It is posted as a customer receipt in Accounting.',
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
        """The bank (or cash) journal the receipts of this company land in."""
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

    @api.onchange('eoi_amount')
    def _onchange_eoi_amount(self):
        self.payment_amount = self.eoi_amount

    def action_register_eoi(self):
        self.ensure_one()
        if self.property_id.state not in ['available']:
            raise UserError(_('Property %s is not available for EOI.', self.property_id.name))
        if self.payment_amount <= 0:
            raise UserError(_('The amount received must be greater than zero.'))

        # The money first: a unit may only be reserved once a receipt is posted
        # against it in Accounting.
        payment = self._resolve_receipt()

        contract_vals = {
            'property_id': self.property_id.id,
            'buyer_id': self.buyer_id.id,
            'joint_buyer_id': self.joint_buyer_id.id if self.joint_buyer_id else False,
            'seller_id': self.property_id.owner_id.id if self.property_id.owner_id else False,
            'sale_price': self.sale_price,
            'currency_id': self.currency_id.id,
            'eoi_amount': self.eoi_amount,
            'eoi_payment_mode': self.eoi_payment_mode,
            'eoi_cheque_no': self.eoi_cheque_no,
            'eoi_cheque_bank': self.eoi_cheque_bank,
            'eoi_cheque_date': self.eoi_cheque_date,
            'eoi_date': self.eoi_date,
            'eoi_expiry_date': self.eoi_expiry_date,
            'eoi_remarks': self.notes,
            'state': 'eoi',
            'company_id': self.env.company.id,
        }

        # Populate purchaser details
        if self.buyer_id:
            contract_vals.update({
                'buyer_name': self.buyer_id.name,
                'buyer_address': self.buyer_id.contact_address or self.buyer_id.city or '',
                'buyer_mobile': self.buyer_id.phone or '',
                'buyer_email': self.buyer_id.email or '',
                'buyer_nationality_id': self.buyer_id.country_id.id if self.buyer_id.country_id else False,
            })
        if self.joint_buyer_id:
            contract_vals.update({
                'joint_buyer_name': self.joint_buyer_id.name,
                'joint_buyer_address': self.joint_buyer_id.contact_address or self.joint_buyer_id.city or '',
                'joint_buyer_mobile': self.joint_buyer_id.phone or '',
                'joint_buyer_email': self.joint_buyer_id.email or '',
                'joint_buyer_nationality_id': self.joint_buyer_id.country_id.id if self.joint_buyer_id.country_id else False,
            })

        contract = self.env['sale.contract'].create(contract_vals)
        contract.write({'eoi_payment_ids': [(4, payment.id)]})
        self.property_id.write({'state': 'eoi'})
        contract.message_post(body=_(
            'EOI registered. Receipt %s of %s posted in Accounting and registered against '
            'unit %s.', payment.display_name, self.payment_amount, self.property_id.display_name))

        return {
            'name': _('Expression of Interest - %s', contract.name),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.contract',
            'res_id': contract.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _resolve_receipt(self):
        """The posted receipt for this EOI, registered against the unit."""
        self.ensure_one()
        memo = _('EOI %s - %s', self.property_id.display_name,
                 self.eoi_cheque_no or self.buyer_id.name)
        amount, date, journal = self.payment_amount, self.payment_date, self.journal_id
        if self.existing_payment_id:
            # An existing receipt carries its own amount and date.
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

    @api.onchange('existing_payment_id')
    def _onchange_existing_payment_id(self):
        if self.existing_payment_id:
            self.payment_amount = self.existing_payment_id.amount
            self.payment_date = self.existing_payment_id.date
