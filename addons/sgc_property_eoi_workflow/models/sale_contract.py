# -*- coding: utf-8 -*-
import base64
import secrets

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import date

class SaleContract(models.Model):
    _inherit = 'sale.contract'

    state = fields.Selection(
        selection_add=[
            ('eoi', 'Expression of Interest (EOI)'),
            ('booked', 'Booked / Reservation'),
            ('confirmed', 'Confirmed Sales'),
            ('spa_issued', 'SPA Issued'),
            ('spa_signed', 'SPA Signed'),
            ('certificate_issued', 'Certificate Issued'),
            ('in_progress', 'In Progress'),
            ('handover', 'Handover'),
            ('refunded', 'Refunded (EOI)'),
        ],
        ondelete={
            'eoi': 'set default',
            'booked': 'set default',
            'confirmed': 'set default',
            'spa_issued': 'set default',
            'spa_signed': 'set default',
            'certificate_issued': 'set default',
            'in_progress': 'set default',
            'handover': 'set default',
            'refunded': 'set default',
        },
        default='eoi',
    )

    # ── EOI Payment Details ───────────────────────────────────────────────
    eoi_amount = fields.Monetary(
        string='EOI Amount (AED)',
        currency_field='currency_id',
        default=0.0,
        help='Initial refundable deposit paid for Expression of Interest.',
    )
    eoi_payment_mode = fields.Selection([
        ('cheque', 'Current Dated Cheque'),
        ('post_dated_cheque', 'Post-Dated Cheque (PDC)'),
        ('card', 'Credit / Debit Card'),
        ('bank_transfer', 'Bank Wire Transfer'),
        ('card_auth', 'Card Authorization Letter'),
        ('cash', 'Cash'),
    ], string='Mode of Payment', default='cheque')
    eoi_cheque_no = fields.Char(string='Cheque / Auth Ref')
    eoi_cheque_bank = fields.Char(string='Drawee Bank Name', default='UAE Licensed Bank')
    eoi_cheque_date = fields.Date(string='Cheque Date / PDC Maturity')
    eoi_date = fields.Date(string='EOI Date', default=fields.Date.context_today)
    eoi_expiry_date = fields.Date(string='Launch / Expiry Date')
    eoi_refundable = fields.Boolean(string='Refundable Deposit', default=True)
    eoi_remarks = fields.Text(
        string='EOI Remarks',
        default='AED 50,000 (CHEQUE) - Fully refundable within 7 days from the booking date. CHQ not to be cashed in.',
    )

    # ── The receipts behind those particulars ─────────────────────────────
    eoi_payment_ids = fields.Many2many(
        'account.payment', 'eoi_contract_payment_rel', 'contract_id', 'payment_id',
        string='Receipts (Accounting)', copy=False, readonly=True,
        help='The posted customer receipts registered against this contract\'s unit.',
    )
    eoi_received_amount = fields.Monetary(
        string='Received (Accounting)', currency_field='currency_id',
        compute='_compute_eoi_received', store=True,
        help='Sum of the posted receipts above.',
    )
    eoi_receipt_state = fields.Selection([
        ('none', 'No Receipt'),
        ('partial', 'Partially Received'),
        ('paid', 'Received'),
    ], compute='_compute_eoi_received', store=True, string='Receipt Status')

    # ── SPA eligibility: the booking amount is the basis ────────────────
    spa_eligible = fields.Boolean(
        string='Ready for SPA', compute='_compute_spa_eligible',
        help='True when the money received against the unit covers the booking amount, '
             'so the SPA can be issued for signing.',
    )
    spa_shortfall = fields.Monetary(
        string='Still Due', currency_field='currency_id', compute='_compute_spa_eligible',
        help='What is still missing against the booking amount.',
    )

    @api.depends('eoi_payment_ids.state', 'eoi_payment_ids.amount',
                 'eoi_payment_ids.payment_type', 'eoi_payment_ids.currency_id',
                 'eoi_amount', 'currency_id')
    def _compute_eoi_received(self):
        helper = self.env['sgc.eoi.receipt.helper']
        states = helper._verified_states()
        for rec in self:
            total = 0.0
            for payment in rec.eoi_payment_ids:
                if payment.payment_type != 'inbound' or payment.state not in states:
                    continue
                total += payment.currency_id._convert(
                    payment.amount, rec.currency_id or rec.company_id.currency_id,
                    rec.company_id or self.env.company,
                    payment.date or fields.Date.context_today(rec))
            rec.eoi_received_amount = total
            if rec.eoi_amount and total + 0.005 >= rec.eoi_amount:
                rec.eoi_receipt_state = 'paid'
            elif total > 0:
                rec.eoi_receipt_state = 'partial'
            else:
                rec.eoi_receipt_state = 'none'

    @api.depends('booking_amount', 'currency_id', 'eoi_payment_ids.amount',
                 'eoi_payment_ids.state', 'property_id')
    def _compute_spa_eligible(self):
        for rec in self:
            received = rec._sgc_received_amount()
            rec.spa_shortfall = max(rec.booking_amount - received, 0.0)
            rec.spa_eligible = bool(rec.booking_amount) and received + 0.005 >= rec.booking_amount

    def _sgc_received_amount(self):
        """What has been received against this contract's unit, in its currency."""
        self.ensure_one()
        helper = self.env['sgc.eoi.receipt.helper']
        states = helper._verified_states()
        payments = self.eoi_payment_ids
        if self.property_id:
            payments |= helper._receipts_for_unit(self.property_id)
        payments = payments.filtered(
            lambda p: p.payment_type == 'inbound' and p.state in states)
        currency = self.currency_id or self.company_id.currency_id
        company = self.company_id or self.env.company
        total = 0.0
        for payment in payments:
            total += payment.currency_id._convert(
                payment.amount, currency, company,
                payment.date or fields.Date.context_today(self))
        return total

    # ── Purchaser Details ────────────────────────────────────────────────
    buyer_name = fields.Char(
        string='Purchaser Name',
        compute='_compute_buyer_name',
        store=True,
        readonly=False,
    )
    buyer_nationality_id = fields.Many2one('res.country', string='Buyer Nationality')
    buyer_passport_no = fields.Char(string='Passport No.')
    buyer_emirates_id = fields.Char(string='Emirates ID')
    buyer_address = fields.Char(string='Residential Address')
    buyer_mobile = fields.Char(string='Mobile Number')
    buyer_email = fields.Char(string='Email Address')
    buyer_authorized_signatory = fields.Char(string='Authorized Signatory')
    buyer_designation = fields.Char(string='Signatory Designation')

    # ── Joint Purchaser Details ──────────────────────────────────────────
    joint_buyer_id = fields.Many2one('res.partner', string='Joint Purchaser')
    joint_buyer_name = fields.Char(string='Joint Purchaser Name')
    joint_buyer_address = fields.Char(string='Joint Purchaser Address')
    joint_buyer_mobile = fields.Char(string='Joint Purchaser Mobile')
    joint_buyer_email = fields.Char(string='Joint Purchaser Email')
    joint_buyer_nationality_id = fields.Many2one('res.country', string='Joint Purchaser Nationality')
    joint_buyer_passport_no = fields.Char(string='Joint Purchaser Passport No.')
    joint_buyer_emirates_id = fields.Char(string='Joint Purchaser Emirates ID')

    # ── Seller / Developer Details ───────────────────────────────────────
    seller_company_name = fields.Char(
        string='Developer / Seller Name',
        compute='_compute_seller_details',
        store=True,
        readonly=False,
    )
    seller_registration_no = fields.Char(
        string='Registration / RERA No.',
        default='Office 323 & 325, Sultan Business Center, Oud Metha, Dubai, 114030, United Arab Emirates',
    )
    seller_office_address = fields.Char(
        string='Seller Office Address',
        default='Office 323 & 325, Sultan Business Center, Oud Metha, Dubai, 114030, United Arab Emirates',
    )
    seller_telephone = fields.Char(string='Seller Telephone', default='+971 4 222 9992')
    seller_signatory = fields.Char(string='Seller Authorized Signatory', default='Authorized Signatory')

    # ── Unit Specifications ──────────────────────────────────────────────
    plot_number = fields.Char(string='Plot / Makani Number', default='Plot 3720562')
    unit_type_code = fields.Char(string='Unit Typology', compute='_compute_unit_specs', store=True, readonly=False)
    unit_size_sqft = fields.Float(string='Unit Size (SqFt)', compute='_compute_unit_specs', store=True, readonly=False)
    additional_remarks = fields.Text(string='Additional Remarks')

    # ── Milestone Dates ──────────────────────────────────────────────────
    booking_date = fields.Date(string='Booking Date')
    spa_issue_date = fields.Date(string='SPA Issued Date')
    spa_signed_date = fields.Date(string='SPA Signed Date')
    certificate_issue_date = fields.Date(string='Certificate Issued Date')
    handover_date = fields.Date(string='Handover Date')

    # -- SPA Digital Signature (portal, mirroring the sale.order quotation flow) --
    signed_by = fields.Char(string='Signed By', readonly=True, copy=False,
                            help='Full name given as the digital signature on the portal.')
    signed_on = fields.Datetime(string='Signed On', readonly=True, copy=False,
                                help='When the SPA was digitally signed on the portal.')
    spa_access_token = fields.Char(string='SPA Signature Access Token', readonly=True, copy=False,
                                   help='One-time link granting access to the signature page.')
    signature = fields.Image(
        string='Signature',
        copy=False,
        help='Customer signature captured on the portal (quotation-style e-signature).',
    )

    @api.depends('buyer_id', 'buyer_id.name')
    def _compute_buyer_name(self):
        for rec in self:
            if rec.buyer_id and rec.buyer_id.name:
                rec.buyer_name = rec.buyer_id.name
            elif not rec.buyer_name:
                rec.buyer_name = ''

    @api.depends('property_id', 'property_id.name', 'property_id.unit_type', 'property_id.area')
    def _compute_unit_specs(self):
        for rec in self:
            if rec.property_id:
                rec.unit_size_sqft = rec.property_id.area or 0.0
                rec.unit_type_code = (rec.property_id.unit_type or '').upper() or '1 BR+S+P'
            else:
                rec.unit_size_sqft = 0.0
                rec.unit_type_code = 'RESIDENTIAL'

    @api.depends('company_id', 'seller_id')
    def _compute_seller_details(self):
        for rec in self:
            if rec.seller_id and rec.seller_id.name:
                rec.seller_company_name = rec.seller_id.name
            elif rec.company_id and rec.company_id.name:
                rec.seller_company_name = rec.company_id.name
            else:
                rec.seller_company_name = 'PARK RESIDENCY REAL ESTATE DEVELOPMENT LLC'

    @api.onchange('buyer_id')
    def _onchange_buyer_id(self):
        if self.buyer_id:
            self.buyer_name = self.buyer_id.name or '' 
            self.buyer_address = self.buyer_id.contact_address or self.buyer_id.city or ''
            self.buyer_mobile = self.buyer_id.phone or ''
            self.buyer_email = self.buyer_id.email or ''
            if self.buyer_id.country_id:
                self.buyer_nationality_id = self.buyer_id.country_id.id

    @api.onchange('joint_buyer_id')
    def _onchange_joint_buyer_id(self):
        if self.joint_buyer_id:
            self.joint_buyer_name = self.joint_buyer_id.name or ''
            self.joint_buyer_address = self.joint_buyer_id.contact_address or self.joint_buyer_id.city or ''
            self.joint_buyer_mobile = self.joint_buyer_id.phone or ''
            self.joint_buyer_email = self.joint_buyer_id.email or ''
            if self.joint_buyer_id.country_id:
                self.joint_buyer_nationality_id = self.joint_buyer_id.country_id.id

    # ── Workflow Transitions ─────────────────────────────────────────────

    def action_convert_to_booked(self):
        self.ensure_one()
        self.write({
            'state': 'booked',
            'booking_date': fields.Date.today(),
        })
        if self.property_id:
            self.property_id.write({'state': 'booked'})
        return True

    def action_cancel_refund_eoi(self):
        """Direct EOI refund (programmatic). UI uses action_cancel_refund_reason."""
        return self._apply_cancellation(None, 'refunded')

    def action_cancel_refund_reason(self):
        """Open the governed-cancel wizard, defaulting to refund."""
        self.ensure_one()
        if self.state in ('cancelled', 'refunded'):
            raise UserError(_('This contract is already %s.', self.state))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Refund / Cancel EOI'),
            'res_model': 'sale.contract.cancel.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref(
                'sgc_offplan_rental_property_management.sale_contract_cancel_wizard_form'
            ).id,
            'target': 'new',
            'context': {
                'default_contract_id': self.id,
                'default_new_state': 'refunded',
            },
        }

    def action_confirm_sale(self):
        self.ensure_one()
        if not self._sgc_posted_receipts():
            raise UserError(_(
                'No posted receipt is registered against %s. A typed amount is not proof of '
                'payment: record the receipt in Accounting against the unit before '
                'confirming the sale.',
                self.property_id.display_name or self.name))
        self.write({
            'state': 'confirmed',
        })
        return True

    def _sgc_posted_receipts(self):
        """The posted receipts behind this contract: its own, plus its unit's."""
        self.ensure_one()
        helper = self.env['sgc.eoi.receipt.helper']
        states = helper._verified_states()
        receipts = self.eoi_payment_ids.filtered(
            lambda p: p.payment_type == 'inbound' and p.state in states)
        if not receipts and self.property_id:
            receipts = helper._receipts_for_unit(self.property_id)
        return receipts

    def action_issue_spa(self):
        """The SPA is issued once the booking amount is covered by money received.

        The booking amount is the basis: the unit has to have received at least
        that much in posted receipts before the sale agreement goes out for
        signing.
        """
        self.ensure_one()
        if not self.booking_amount:
            raise UserError(_(
                'Set the booking amount before issuing the SPA: it is the basis for '
                'deciding that the money against unit %s is in.',
                self.property_id.display_name or self.name))
        received = self._sgc_received_amount()
        if received + 0.005 < self.booking_amount:
            raise UserError(_(
                'Unit %s has received %s against a booking amount of %s, so the SPA '
                'cannot be issued for signing yet. Still due: %s.',
                self.property_id.display_name or self.name,
                received, self.booking_amount, self.booking_amount - received))
        self.write({
            'state': 'spa_issued',
            'spa_issue_date': fields.Date.today(),
        })
        return True

    def action_sign_spa(self):
        self.ensure_one()
        self.write({
            'state': 'spa_signed',
            'spa_signed_date': fields.Date.today(),
        })
        if self.property_id:
            self.property_id.write({'state': 'sold'})
        return True

    def action_cancel_contract(self):
        """Backward-compatible direct cancel; the header uses action_cancel_reason."""
        return self.action_cancel()

    def action_issue_certificate(self):
        self.ensure_one()
        if self.state != 'spa_signed':
            raise UserError(_('Only SPA-signed contracts can have their certificate issued.'))
        self.write({
            'state': 'certificate_issued',
            'certificate_issue_date': fields.Date.today(),
        })
        return True

    def action_start_construction(self):
        self.ensure_one()
        if self.state != 'certificate_issued':
            raise UserError(_('Construction can only start after the certificate is issued.'))
        self.write({'state': 'in_progress'})
        return True

    def action_mark_handover(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(_('Handover is only possible for contracts in progress.'))
        self.write({
            'state': 'handover',
            'handover_date': fields.Date.today(),
        })
        return True

    def _spa_has_to_be_signed(self):
        """Mirror sale.order._has_to_be_signed for the SPA portal signature."""
        return self.filtered(lambda c: c.state == 'spa_issued')

    def _ensure_spa_access_token(self):
        self.ensure_one()
        if not self.spa_access_token:
            self.spa_access_token = secrets.token_urlsafe(32)
        return self.spa_access_token

    def _spa_sign_url(self):
        self.ensure_one()
        return '/my/contract/sale/%s/spa/sign?token=%s' % (
            self.id, self._ensure_spa_access_token())

    def action_send_spa(self):
        '''Open the 'Send SPA by Email' composer (SPA PDF attached via template).'''
        self.ensure_one()
        self._ensure_spa_access_token()
        template = self.env.ref('sgc_property_eoi_workflow.spa_signature_email')
        ctx = {
            'default_model': self._name,
            'default_res_ids': self.ids,
            'default_use_template': True,
            'default_template_id': template.id,
            'default_composition_mode': 'comment',
            'force_email': True,
            'hide_mail_template_management_options': True,
        }
        compose = self.env['mail.compose.message'].with_context(**ctx).create({})
        return {
            'name': _('Send SPA by Email'),
            'type': 'ir.actions.act_window',
            'view_mode': 'form',
            'res_model': 'mail.compose.message',
            'res_id': compose.id,
            'target': 'new',
            'context': ctx,
        }

    def spa_sign_from_portal(self, signed_by_name=None, signature=None):
        '''Record the portal digital signature (quotation-style): SPA Issued -> SPA Signed.'''
        self.ensure_one()
        if self.state != 'spa_issued':
            raise UserError(_('This contract is not awaiting signature (SPA Issued).'))
        if not signature:
            raise UserError(_('Signature is missing.'))
        name = (signed_by_name or self.buyer_name or self.buyer_id.name or '').strip()
        if not name:
            raise UserError(_('Please enter your full name as signature.'))
        self.write({
            'state': 'spa_signed',
            'spa_signed_date': fields.Date.today(),
            'signed_by': name,
            'signed_on': fields.Datetime.now(),
            'signature': signature,
        })
        if self.property_id:
            self.property_id.write({'state': 'sold'})
        pdf_content, _report_type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'sgc_offplan_rental_property_management.action_report_sales_purchase_agreement_contract',
            res_ids=self.ids,
        )
        attachment = self.env['ir.attachment'].sudo().create({
            'name': 'SPA - %s - Signed.pdf' % (self.name or 'Contract').replace('/', '-'),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/pdf',
            'datas': base64.b64encode(pdf_content),
        })
        self.message_post(
            body=_('The SPA was digitally signed on the portal by %s. '
                   'The signed agreement is attached.', name),
            attachment_ids=[attachment.id],
        )
        return True

    def action_print_eoi_agreement(self):
        self.ensure_one()
        return self.env.ref('sgc_property_eoi_workflow.action_report_eoi_agreement').report_action(self)

    def action_print_reservation_form(self):
        self.ensure_one()
        return self.env.ref('sgc_property_eoi_workflow.action_report_reservation_form').report_action(self)
