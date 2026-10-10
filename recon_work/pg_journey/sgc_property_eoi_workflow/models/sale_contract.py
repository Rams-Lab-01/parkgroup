# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import date

class SaleContract(models.Model):
    _inherit = 'sale.contract'

    # Lifecycle: draft -> eoi -> booked -> spa_issued -> spa_signed -> registered
    #            -> waiting_handover -> completed, plus cancelled (resettable
    #            to draft) and refunded for a dead EOI.
    #
    # This REDEFINES the whole selection rather than using selection_add,
    # because 'signed' and 'confirmed' were dropped on request and
    # selection_add can only append - it cannot remove a value that the base
    # module (sgc_offplan_rental_property_management) already declares.
    # Every base value must be repeated here or it disappears from the field.
    #
    # Legacy rows in 'signed' are migrated to 'spa_signed' by
    # tools/migrate_signed_to_spa_signed.py before this module is upgraded.
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('eoi', 'Expression of Interest (EOI)'),
            ('booked', 'Booked / Reservation'),
            ('spa_issued', 'SPA Issued'),
            ('spa_signed', 'SPA Signed'),
            ('registered', 'Registered'),
            ('waiting_handover', 'Waiting for Handover'),
            ('completed', 'Completed'),
            ('cancelled', 'Cancelled'),
            ('refunded', 'Refunded (EOI)'),
        ],
        ondelete={
            'signed': 'set default',
            'confirmed': 'set default',
            'eoi': 'set default',
            'booked': 'set default',
            'spa_issued': 'set default',
            'spa_signed': 'set default',
            'registered': 'set default',
            'waiting_handover': 'set default',
            'refunded': 'set default',
        },
        default='eoi',
        string='Status',
        tracking=True,
    )

    # States that mean the unit is sold and must not be re-sold.
    SOLD_STATES = ('spa_signed', 'registered', 'waiting_handover', 'completed')

    # States in which the unit is held away from the market.
    RESERVED_STATES = ('eoi', 'booked', 'spa_issued', 'spa_signed',
                       'registered', 'waiting_handover')

    # ── EOI Payment Details ───────────────────────────────────────────────
    eoi_amount = fields.Monetary(
        string='EOI Amount (AED)',
        currency_field='currency_id',
        default=0.0,
        help='Initial refundable deposit paid for Expression of Interest.',
    )
    eoi_payment_mode = fields.Selection([
        ('cheque', 'Current Dated Cheque'),
        ('card', 'Credit / Debit Card'),
        ('bank_transfer', 'Bank Wire Transfer'),
        ('card_auth', 'Card Authorization Letter'),
        ('cash', 'Cash'),
    ], string='Mode of Payment', default='cheque')
    eoi_cheque_no = fields.Char(string='Cheque / Auth Ref')
    eoi_cheque_bank = fields.Char(string='Drawee Bank Name', default='UAE Licensed Bank')
    eoi_date = fields.Date(string='EOI Date', default=fields.Date.context_today)
    eoi_expiry_date = fields.Date(string='Launch / Expiry Date')
    eoi_refundable = fields.Boolean(string='Refundable Deposit', default=True)
    eoi_remarks = fields.Text(
        string='EOI Remarks',
        default='AED 50,000 (CHEQUE) - Fully refundable within 7 days from the booking date. CHQ not to be cashed in.',
    )

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
        self.ensure_one()
        self.write({'state': 'refunded'})
        if self.property_id:
            self.property_id.write({'state': 'available'})
        return True

    def action_complete(self):
        """Waiting for Handover -> Completed; the unit becomes sold here.

        The base module's action_complete required state == 'signed'. That
        state was dropped in favour of the SPA steps, so the handover close
        is re-anchored to 'waiting_handover' here.
        """
        for contract in self:
            if contract.state != 'waiting_handover':
                raise UserError(_(
                    'Only a contract waiting for handover can be completed.'))
            contract.write({'state': 'completed'})
            if contract.property_id:
                contract.property_id.write({'state': 'sold'})
        return True

    def action_confirm_sale(self):
        """Deprecated: the 'confirmed' state was removed.

        Kept as a no-arg shim so an old bookmark or a saved action does not
        raise a missing-method error. Booked contracts now go straight to
        SPA Issued via action_issue_spa.
        """
        return self.action_issue_spa()

    def action_issue_spa(self):
        self.ensure_one()
        if self.state != 'booked':
            raise UserError(_('Only booked contracts can have an SPA issued.'))
        self.write({
            'state': 'spa_issued',
            'spa_issue_date': fields.Date.today(),
        })
        return True

    def action_sign_spa(self):
        self.ensure_one()
        if self.state != 'spa_issued':
            raise UserError(_('Only an issued SPA can be signed.'))
        self.write({
            'state': 'spa_signed',
            'spa_signed_date': fields.Date.today(),
        })
        # Signing the SPA takes the unit off the market. The property is only
        # 'sold' for good once the deed is registered and handed over, but it
        # must never be re-sold in the meantime.
        if self.property_id:
            self.property_id.write({'state': 'sold'})
        return True

    def action_register(self):
        """SPA signed -> Registered (title deed issued)."""
        self.ensure_one()
        if self.state != 'spa_signed':
            raise UserError(_('Only a signed SPA can be registered.'))
        reg = self.offplan_reg_status if 'offplan_reg_status' in self._fields else False
        if reg and reg not in ('issued', 'converted'):
            raise UserError(_(
                'Issue the off-plan registration before marking the contract '
                'as registered (current status: %s).') % reg)
        self.write({'state': 'registered'})
        return True

    def action_waiting_handover(self):
        """Registered -> Waiting for Handover."""
        self.ensure_one()
        if self.state != 'registered':
            raise UserError(_('Only a registered contract can await handover.'))
        self.write({'state': 'waiting_handover'})
        return True

    def action_cancel_contract(self):
        self.ensure_one()
        if self.state in ('completed', 'cancelled'):
            raise UserError(_('Completed or already cancelled contracts cannot be cancelled.'))
        self.write({'state': 'cancelled'})
        if self.property_id:
            self.property_id.write({'state': 'available'})
        return True

    def action_draft(self):
        """Cancelled -> Draft.

        A reset must not leave the estate inconsistent, so this refuses
        rather than silently half-restoring:
          - another live contract already holds the unit  -> would double-book
          - posted invoices exist                          -> would orphan AR
        """
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only cancelled contracts can be reset to draft.'))
            invoices = rec.invoice_ids.filtered(
                lambda m: m.state == 'posted')
            if invoices:
                raise UserError(_(
                    'Contract %s has %d posted invoice(s). Cancel or reverse '
                    'them before resetting to draft.') % (
                        rec.name or _('this contract'), len(invoices)))
            if rec.property_id:
                rival = self.search([
                    ('id', '!=', rec.id),
                    ('property_id', '=', rec.property_id.id),
                    ('state', 'in', self.RESERVED_STATES),
                ], limit=1)
                if rival:
                    raise UserError(_(
                        'Unit %s is already held by contract %s. Resolve that '
                        'contract before resetting this one.') % (
                            rec.property_id.display_name, rival.name or rival.id))
            rec.write({'state': 'draft'})
            if rec.property_id:
                rec.property_id.write({'state': 'available'})
            if 'offplan_reg_status' in rec._fields \
                    and rec.offplan_reg_status == 'cancelled':
                rec.write({'offplan_reg_status': 'pending'})
        return True

    def action_print_eoi_agreement(self):
        self.ensure_one()
        return self.env.ref('sgc_property_eoi_workflow.action_report_eoi_agreement').report_action(self)

    def action_print_reservation_form(self):
        self.ensure_one()
        return self.env.ref('sgc_property_eoi_workflow.action_report_reservation_form').report_action(self)
