# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta


class RERAFormA(models.Model):
    _name = 'rera.form.a'
    _description = 'RERA Form A - Listing Agreement'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    # ------------------------------------------------------------------
    # Basic Fields
    # ------------------------------------------------------------------
    name = fields.Char(
        string='Form A Reference', required=True,
        default=lambda self: self._get_default_reference(),
        copy=False)

    property_id = fields.Many2one(
        'property.details', string='Property', required=True,
        ondelete='restrict')

    owner_id = fields.Many2one(
        'res.partner', string='Owner/Landlord', required=True,
        domain="[('user_type', '=', 'landlord')]",
        context={'default_user_type': 'landlord'})

    agent_id = fields.Many2one(
        'res.partner', string='Listing Agent', required=True,
        domain="[('user_type', '=', 'broker')]",
        context={'default_user_type': 'broker'})

    broker_id = fields.Many2one(
        'res.partner', string='Broker/Company',
        help='Real estate brokerage company')

    buyer_id = fields.Many2one(
        'res.partner', string='Buyer/Tenant')

    # ------------------------------------------------------------------
    # Commission
    # ------------------------------------------------------------------
    commission_type = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percentage', 'Percentage'),
    ], string='Commission Type', default='percentage')

    commission_amount = fields.Float(
        string='Commission Amount/Percentage', default=2.0,
        help='Commission amount or percentage (DLD default: 2%)')

    commission_total = fields.Monetary(
        string='Total Commission', currency_field='currency_id',
        compute='_compute_commission_total', store=True)

    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id)

    # ------------------------------------------------------------------
    # Dates
    # ------------------------------------------------------------------
    agreement_date = fields.Date(
        string='Agreement Date', required=True,
        default=lambda self: fields.Date.today())

    valid_from = fields.Date(
        string='Valid From', required=True,
        default=lambda self: fields.Date.today())

    valid_until = fields.Date(
        string='Valid Until', required=True,
        default=lambda self: fields.Date.today() + relativedelta(months=3) - timedelta(days=1),
        help='Form A typically valid for 90 days from issue')

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    state = fields.Selection([
        ('draft', 'Draft'),
        ('signed', 'Signed'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='draft', tracking=True)

    # ------------------------------------------------------------------
    # DLD Permit
    # ------------------------------------------------------------------
    permit_number = fields.Char(
        string='Trakheesi Permit #',
        help='Linked DLD permit number obtained after Form A registration')

    permit_status = fields.Selection([
        ('not_applied', 'Not Applied'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Permit Status', default='not_applied')

    dld_permit_number = fields.Char(
        string='DLD Permit Number',
        help='DLD Trakheesi permit number assigned after Form A registration')

    permit_issue_date = fields.Date(
        string='Permit Issue Date',
        help='Date when the DLD permit was issued')

    permit_expiry_date = fields.Date(
        string='Permit Expiry Date',
        help='Expiry date of the DLD permit')

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    listing_price = fields.Monetary(
        string='Listing Price', currency_field='currency_id',
        help='Price as agreed in Form A')

    listing_type = fields.Selection([
        ('sale', 'For Sale'),
        ('rent', 'For Rent'),
        ('both', 'Both'),
    ], string='Listing Type', default='sale')

    is_exclusive = fields.Boolean(
        string='Exclusive Agreement',
        help='Exclusive right to sell/rent')

    notes = fields.Text(string='Notes')

    # ------------------------------------------------------------------
    # Owner Identification (DLD-required)
    # ------------------------------------------------------------------
    owner_emirates_id = fields.Char(
        string='Owner Emirates ID',
        help='Emirates ID of the owner/seller')

    owner_passport = fields.Char(
        string='Owner Passport (Non-Resident)',
        help='Passport number for non-resident owner')

    owner_nationality = fields.Char(
        string='Owner Nationality',
        help='Nationality of the owner')

    owner_type = fields.Selection([
        ('individual', 'Individual'),
        ('company', 'Company / Entity'),
    ], string='Owner Type', default='individual',
        help='Whether the owner is an individual or a corporate entity')

    # ------------------------------------------------------------------
    # Brokerage Firm (DLD-required regulatory IDs)
    # ------------------------------------------------------------------
    brokerage_orn = fields.Char(
        string='Office Registration Number (ORN)',
        help='DLD Office Registration Number of the brokerage firm')

    brokerage_brn = fields.Char(
        string='Broker Registration Number (BRN)',
        help='DLD Broker Registration Number of the brokerage firm')

    brokerage_trade_license = fields.Char(
        string='Trade Licence Number',
        help='DED Trade Licence number of the brokerage firm')

    brokerage_po_box = fields.Char(
        string='Brokerage PO Box',
        help='PO Box of the brokerage firm')

    agent_brn = fields.Char(
        string='Agent BRN',
        help='Individual broker registration number of the listing agent')

    # ------------------------------------------------------------------
    # Property Detail Extensions
    # ------------------------------------------------------------------
    property_community = fields.Char(
        string='Property Community',
        help='Community / district name (e.g., Downtown Dubai, Palm Jumeirah)')

    property_building_name = fields.Char(
        string='Property Building Name',
        help='Building name within the community')

    property_title_deed_number = fields.Char(
        string='Title Deed Number',
        help='DLD Title Deed number')

    property_parking = fields.Char(
        string='Parking Allocation',
        help='Number / type of parking spaces')

    # ------------------------------------------------------------------
    # Listing Terms Extensions
    # ------------------------------------------------------------------
    minimum_price = fields.Monetary(
        string='Minimum Acceptable Price', currency_field='currency_id',
        help='Lowest price the owner will accept')

    auto_renew = fields.Boolean(
        string='Auto-Renew at Expiry',
        help='If True, agreement auto-renews for another period unless terminated')

    commission_payer = fields.Selection([
        ('seller', 'Owner / Seller'),
        ('buyer', 'Buyer'),
        ('split', 'Split (50/50)'),
    ], string='Commission Paid By', default='seller')

    commission_trigger = fields.Selection([
        ('form_f_execution', 'On Form F Execution'),
        ('dld_transfer', 'On DLD Transfer'),
        ('keys_handover', 'On Keys Handover'),
    ], string='Commission Payable On', default='form_f_execution')

    marketing_channels = fields.Text(
        string='Approved Marketing Channels',
        help='Channels where the broker is authorised to advertise the property')

    notice_period_days = fields.Integer(
        string='Notice Period (Days)', default=7,
        help='Minimum written notice required to terminate this agreement')

    # ------------------------------------------------------------------
    # Company
    # ------------------------------------------------------------------
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)

    # ------------------------------------------------------------------
    # Default / Name Generation
    # ------------------------------------------------------------------
    @api.model
    def _get_default_reference(self):
        """Generate auto-incrementing reference: FA/{YYYY}/XXXXX"""
        seq = self.env['ir.sequence'].next_by_code('rera.form.a')
        if seq:
            return seq
        year = fields.Date.today().year
        last = self.search([], order='id desc', limit=1)
        next_num = (int(last.name.split('/')[-1]) + 1) if last and last.name else 1
        return 'FA/{:04d}/{:05d}'.format(year, next_num)

    # ------------------------------------------------------------------
    # Computed Fields
    # ------------------------------------------------------------------
    @api.depends('listing_price', 'commission_amount', 'commission_type')
    def _compute_commission_total(self):
        for rec in self:
            if rec.commission_type == 'percentage':
                rec.commission_total = rec.listing_price * (rec.commission_amount / 100.0) if rec.listing_price else 0.0
            else:
                rec.commission_total = rec.commission_amount

    # ------------------------------------------------------------------
    # State Transitions
    # ------------------------------------------------------------------
    def action_sign(self):
        for rec in self:
            rec.state = 'signed'

    def action_activate(self):
        for rec in self:
            rec.state = 'active'

    def action_expire(self):
        for rec in self:
            rec.state = 'expired'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'

    # ------------------------------------------------------------------
    # Smart-button: open linked property.details
    # ------------------------------------------------------------------
    def action_open_linked_property(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Property',
            'res_model': 'property.details',
            'res_id': self.property_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------
    @api.constrains('valid_from', 'valid_until')
    def _check_valid_dates(self):
        for rec in self:
            if rec.valid_from and rec.valid_until and rec.valid_until <= rec.valid_from:
                raise ValidationError(
                    _('Valid Until must be after Valid From date.'))

    @api.constrains('property_id', 'state')
    def _check_unique_per_property(self):
        for rec in self:
            if rec.state not in ('cancelled', 'expired'):
                existing = self.search([
                    ('property_id', '=', rec.property_id.id),
                    ('state', 'not in', ('cancelled', 'expired')),
                    ('id', '!=', rec.id),
                ])
                if existing:
                    raise ValidationError(
                        _('An active Form A already exists for this property. '
                          'Please cancel or expire the existing Form A first.'))
