from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

PAYMENT_MODES = [
    ('cheque', 'Cheque'), ('bank_transfer', 'Bank Transfer'), ('card', 'Card'),
    ('cash', 'Cash'), ('card_authorization', 'Card Authorization Letter'), ('other', 'Other'),
]


class PropertyEoi(models.Model):
    _name = 'property.eoi'
    _description = 'Expression of Interest (EOI)'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    _one_active_per_unit = models.UniqueIndex(
        "(property_id) WHERE state = 'active'", 'This unit already has an active EOI.')

    name = fields.Char(string='EOI Reference', default=lambda self: _('New'), copy=False, readonly=True,
                       index=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active - Unit Reserved'),
        ('converted', 'Converted to Booking'),
        ('cancelled', 'Cancelled / Released'),
        ('expired', 'Expired'),
    ], default='draft', required=True, copy=False, tracking=True, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)

    # --- unit / project
    property_id = fields.Many2one('property.details', string='Unit', required=True, index=True, tracking=True,
                                  ondelete='restrict')
    project_id = fields.Many2one(related='property_id.project_id', store=True, index=True)
    unit_price = fields.Monetary(string='List Price', currency_field='currency_id', tracking=True,
                                 help='Price at the time of the EOI (snapshot; later price changes do not alter it).')

    # --- purchaser (live link + snapshot of the details printed on the document)
    partner_id = fields.Many2one('res.partner', string='Purchaser', required=True, index=True, tracking=True)
    purchaser_nationality = fields.Char(string='Nationality')
    purchaser_passport_no = fields.Char(string='Passport No.')
    purchaser_phone = fields.Char(string='Mobile')
    purchaser_email = fields.Char(string='Email')
    purchaser_address = fields.Char(string='Address')
    joint_partner_id = fields.Many2one('res.partner', string='Joint Purchaser')
    joint_nationality = fields.Char(string='Joint Nationality')
    joint_passport_no = fields.Char(string='Joint Passport No.')

    # --- EOI details
    eoi_date = fields.Datetime(string='EOI Date', default=fields.Datetime.now, required=True, tracking=True)
    valid_until = fields.Date(string='Valid Until', tracking=True,
                              help='After this date an active EOI expires and the unit is released.')
    user_id = fields.Many2one('res.users', string='Salesperson', default=lambda self: self.env.user, tracking=True)
    source_id = fields.Many2one('utm.source', string='Source / Channel')
    notes = fields.Text(string='Notes')

    # --- EOI amount / payment (real accounting payments only)
    amount = fields.Monetary(string='EOI Amount', currency_field='currency_id', tracking=True)
    payment_mode = fields.Selection(PAYMENT_MODES, string='Mode of Payment')
    payment_reference = fields.Char(string='Payment Reference / Cheque No.')
    payment_ids = fields.Many2many('account.payment', 'property_eoi_payment_rel', 'eoi_id', 'payment_id',
                                   string='Payments', copy=False)
    amount_paid = fields.Monetary(compute='_compute_payment', currency_field='currency_id', string='Amount Paid')
    amount_outstanding = fields.Monetary(compute='_compute_payment', currency_field='currency_id',
                                         string='Outstanding')
    payment_state = fields.Selection([
        ('not_required', 'No EOI Amount'),
        ('pending', 'Pending'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
    ], compute='_compute_payment', string='Payment Status')

    # --- traceability
    contract_id = fields.Many2one('sale.contract', string='Contract', readonly=True, copy=False, index=True)
    booking_id = fields.Many2one('property.vendor', string='Booking', readonly=True, copy=False, index=True)
    converted_date = fields.Datetime(readonly=True, copy=False)
    cancel_reason = fields.Text(string='Cancellation / Release Reason', readonly=True, copy=False)
    cancel_date = fields.Datetime(readonly=True, copy=False)
    cancel_user_id = fields.Many2one('res.users', string='Cancelled By', readonly=True, copy=False)
    cancel_amount_paid = fields.Monetary(string='Paid at Cancellation', currency_field='currency_id',
                                         readonly=True, copy=False)
    is_expired = fields.Boolean(compute='_compute_is_expired')

    # ------------------------------------------------------------------ computes / defaults
    @api.depends('payment_ids.state', 'payment_ids.amount', 'amount', 'currency_id')
    def _compute_payment(self):
        helper = self.env['sgc.payment.helper']
        for rec in self:
            paid = helper._counted_amount(rec.payment_ids, rec.currency_id or rec.company_id.currency_id,
                                          rec.company_id)
            rec.amount_paid = paid
            rec.amount_outstanding = max(rec.amount - paid, 0.0)
            if rec.amount <= 0:
                rec.payment_state = 'not_required'
            elif paid + 0.005 >= rec.amount:
                rec.payment_state = 'paid'
            elif paid > 0:
                rec.payment_state = 'partial'
            else:
                rec.payment_state = 'pending'

    @api.depends('valid_until', 'state')
    def _compute_is_expired(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.is_expired = bool(rec.state == 'active' and rec.valid_until and rec.valid_until < today)

    @api.onchange('property_id')
    def _onchange_property_id(self):
        prop = self.property_id
        if prop:
            self.unit_price = prop.sale_price or prop.price
            days = self.company_id.sgc_eoi_validity_days
            if days and not self.valid_until:
                self.valid_until = fields.Date.context_today(self) + timedelta(days=days)

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        self._fill_purchaser_snapshot()

    def _fill_purchaser_snapshot(self):
        for rec in self:
            p = rec.partner_id
            if not p:
                continue
            nationality = ''
            if 'sgc_nationality_id' in p._fields and p.sgc_nationality_id:
                nationality = p.sgc_nationality_id.name
            rec.purchaser_nationality = rec.purchaser_nationality or nationality or p.country_id.name or ''
            if 'sgc_passport_no' in p._fields:
                rec.purchaser_passport_no = rec.purchaser_passport_no or p.sgc_passport_no or ''
            rec.purchaser_phone = rec.purchaser_phone or p.phone or ''
            rec.purchaser_email = rec.purchaser_email or p.email or ''
            rec.purchaser_address = rec.purchaser_address or ', '.join(
                x for x in (p.street, p.city, p.country_id.name) if x)

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_('The EOI amount cannot be negative.'))

    @api.constrains('valid_until', 'eoi_date')
    def _check_validity(self):
        for rec in self:
            if rec.valid_until and rec.eoi_date and rec.valid_until < rec.eoi_date.date():
                raise ValidationError(_('"Valid Until" cannot be before the EOI date.'))

    # ------------------------------------------------------------------ CRUD
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('property.eoi') or _('New')
            if vals.get('property_id') and not vals.get('unit_price'):
                prop = self.env['property.details'].browse(vals['property_id'])
                vals['unit_price'] = prop.sale_price or prop.price
        records = super().create(vals_list)
        records._fill_purchaser_snapshot()
        return records

    def unlink(self):
        if any(rec.state != 'draft' for rec in self):
            raise UserError(_('Only draft EOIs can be deleted. Cancel the EOI instead so the history is kept.'))
        return super().unlink()

    # ------------------------------------------------------------------ helpers
    def _seller_partner(self):
        self.ensure_one()
        return self.project_id.developer_id or self.company_id.partner_id

    def _release_unit(self):
        """Return the unit to Available, but only if it is still held by THIS EOI (never by a booking)."""
        for rec in self:
            prop = rec.property_id
            if prop.state == 'eoi' and not prop.eoi_ids.filtered(lambda e: e.state == 'active' and e != rec):
                prop.write({'state': 'available'})

    # ------------------------------------------------------------------ workflow
    def action_confirm(self):
        """Draft -> Active: the unit is reserved under EOI and the EOI contract is opened."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only a draft EOI can be activated.'))
            prop = rec.property_id
            if prop.state != 'available':
                raise UserError(_('%(unit)s is not Available (status: %(state)s), so it cannot be reserved under EOI.',
                                  unit=prop.display_name, state=prop._sgc_state_label(prop.state)))
            if rec.amount < 0:
                raise UserError(_('The EOI amount cannot be negative.'))
            rec.unit_price = rec.unit_price or prop.sale_price or prop.price
            rec.state = 'active'
            prop.write({'state': 'eoi'})
            rec._ensure_contract()
            rec.message_post(body=_('EOI activated. Unit %s is reserved under Expression of Interest (not a booking).',
                                    prop.display_name))

    def _ensure_contract(self):
        self.ensure_one()
        if self.contract_id:
            return self.contract_id
        seller = self._seller_partner()
        contract = self.env['sale.contract'].create({
            'property_id': self.property_id.id,
            'buyer_id': self.partner_id.id,
            'seller_id': seller.id,
            'sale_price': self.unit_price,
            'currency_id': self.currency_id.id,
            'contract_date': fields.Date.context_today(self),
            'booking_amount': self.amount,
            'company_id': self.company_id.id,
            'notes': self.notes,
            'state': 'eoi',
            'eoi_id': self.id,
        })
        self.contract_id = contract
        return contract

    def action_convert_to_booking(self):
        """Active EOI -> Booked. The same contract moves to the Booked stage; EOI payments carry over."""
        self.ensure_one()
        if self.state != 'active':
            raise UserError(_('Only an active EOI can be converted to a booking.'))
        if self.is_expired:
            raise UserError(_('This EOI has expired (valid until %s). Extend the validity first.', self.valid_until))
        prop = self.property_id
        if prop.state != 'eoi':
            raise UserError(_('The unit is no longer under EOI (status: %s).', prop._sgc_state_label(prop.state)))
        contract = self._ensure_contract()
        booking = self.env['property.vendor'].create({
            'property_id': prop.id,
            'vendor_id': self._seller_partner().id,
            'customer_id': self.partner_id.id,
            'sale_price': self.unit_price,
            'currency_id': self.currency_id.id,
            'company_id': self.company_id.id,
            'sale_contract_id': contract.id,
            'eoi_id': self.id,
            'salesperson_id': self.user_id.id or self.env.user.id,
            'payment_ids': [(6, 0, self.payment_ids.ids)],
            'notes': self.notes,
            'date': fields.Date.context_today(self),
        })
        contract.booking_id = booking
        booking.action_confirm()
        self.write({'state': 'converted', 'booking_id': booking.id, 'converted_date': fields.Datetime.now()})
        self.message_post(body=_('Converted to booking %s. The EOI contract moved to the Booked stage.', booking.name))
        return {'type': 'ir.actions.act_window', 'res_model': 'property.vendor', 'res_id': booking.id,
                'view_mode': 'form', 'target': 'current'}

    def action_cancel(self, reason=None):
        """Cancel / release. Only Draft or Active EOIs: a converted EOI belongs to a booking and must be
        cancelled there, so a unit that progressed can never be released by accident."""
        for rec in self:
            if rec.state == 'converted':
                raise UserError(_('EOI %s was converted to booking %s. Cancel the booking instead.',
                                  rec.name, rec.booking_id.name))
            if rec.state in ('cancelled', 'expired'):
                raise UserError(_('EOI %s is already %s.', rec.name, rec.state))
            was_active = rec.state == 'active'
            rec.write({
                'state': 'cancelled', 'cancel_reason': reason or _('Cancelled'), 'cancel_date': fields.Datetime.now(),
                'cancel_user_id': self.env.user.id, 'cancel_amount_paid': rec.amount_paid,
            })
            if was_active:
                rec._release_unit()
                if rec.contract_id and rec.contract_id.state == 'eoi':
                    rec.contract_id._sgc_cancel_without_release()
            rec.message_post(body=_('EOI cancelled by %(user)s. Reason: %(reason)s. Amount paid at cancellation: '
                                    '%(paid)s (refund / forfeiture is handled in Accounting per the EOI terms).',
                                    user=self.env.user.name, reason=reason or '-', paid=rec.amount_paid))
        return True

    def action_open_cancel_wizard(self):
        self.ensure_one()
        return {'type': 'ir.actions.act_window', 'name': _('Cancel / Release EOI'), 'res_model': 'property.eoi.cancel.wizard',
                'view_mode': 'form', 'target': 'new', 'context': {'default_eoi_id': self.id}}

    def action_set_draft(self):
        for rec in self:
            if rec.state not in ('cancelled', 'expired'):
                raise UserError(_('Only a cancelled or expired EOI can be reset to draft.'))
            rec.write({'state': 'draft', 'cancel_reason': False, 'cancel_date': False, 'cancel_user_id': False})

    @api.model
    def _cron_expire_eois(self):
        today = fields.Date.context_today(self)
        for rec in self.search([('state', '=', 'active'), ('valid_until', '<', today)]):
            rec.action_cancel(reason=_('Expired on %s (validity period elapsed).', rec.valid_until))
            rec.state = 'expired'
        return True

    # ------------------------------------------------------------------ payment
    def action_record_payment(self):
        self.ensure_one()
        if self.state not in ('draft', 'active'):
            raise UserError(_('Payments can only be recorded on a draft or active EOI.'))
        return {'type': 'ir.actions.act_window', 'name': _('Record EOI Payment'), 'res_model': 'property.eoi.payment.wizard',
                'view_mode': 'form', 'target': 'new',
                'context': {'default_eoi_id': self.id, 'default_amount': self.amount_outstanding or self.amount}}

    # ------------------------------------------------------------------ smart buttons / reports
    def action_view_contract(self):
        self.ensure_one()
        return self.contract_id._get_records_action() if self.contract_id else False

    def action_view_booking(self):
        self.ensure_one()
        return self.booking_id._get_records_action() if self.booking_id else False

    def action_print_eoi(self):
        self.ensure_one()
        return self.env.ref('sgc_property_eoi.action_report_property_eoi').report_action(self)

    def _report_data(self):
        self.ensure_one()
        company = self.company_id
        from .res_company import DEFAULT_EOI_NOTICE, DEFAULT_EOI_TERMS, DEFAULT_DOC_FOOTER
        lines = lambda txt: [ln.strip() for ln in (txt or '').splitlines() if ln.strip()]
        seller = self._seller_partner()
        return {
            'seller': seller,
            'notice': company.sgc_eoi_notice or DEFAULT_EOI_NOTICE,
            'terms': lines(company.sgc_eoi_terms or DEFAULT_EOI_TERMS),
            'footer': company.sgc_doc_footer or DEFAULT_DOC_FOOTER,
        }
