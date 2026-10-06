# -*- coding: utf-8 -*-
# Scope B: Booking-side sales consolidation
# Adds sale_type, payment tracking, confirm-sale action, and warning wizard
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.sgc_offplan_rental_property_management.services import sgc_audit_internal_service


class PropertyVendor(models.Model):
    _name = 'property.vendor'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _description = 'Property Vendor / Booking'
    _order = 'id desc'

    name = fields.Char(string='Vendor Reference', required=True, tracking=True,
                       default=lambda self: _('New'), copy=False)
    property_id = fields.Many2one('property.details', string='Property')
    vendor_id = fields.Many2one('res.partner', string='Vendor', required=True)
    customer_id = fields.Many2one('res.partner', string='Customer')
    broker_id = fields.Many2one('res.partner', string='Broker',
                                domain=[('user_type', '=', 'broker')])
    sale_price = fields.Monetary(string='Sale Price', currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    # Bridge to canonical sale.contract model
    sale_contract_id = fields.Many2one(
        'sale.contract', string='Sale Contract',
        help='Linked sale.contract record. When set, this booking/vendor record is bridged to the canonical sales model.')

    payment_schedule_id = fields.Many2one(
        'payment.schedule', string='Payment Plan',
        domain=[('schedule_type', '=', 'sale')],
        help='Payment plan shown on the printed Sales Offer for this booking. '
             'Projected from the selected schedule when no linked contract has '
             'generated installments yet.',)

    contract_date = fields.Date(string='Contract Date')
    signed_via_portal = fields.Boolean(
        string='Signed via Portal',
        default=False,
        help='Marked when the customer clicked "I agree & sign" from the portal.')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    sold_seq = fields.Char(string='Sold Seq')
    date = fields.Date(string='Date')
    notes = fields.Text(string='Notes')

    # -------------------------------------------------------------------------
    # COMMISSION DISTRIBUTION (multi-party, per-beneficiary lines)
    # -------------------------------------------------------------------------
    commission_line_ids = fields.One2many(
        'property.vendor.commission.line', 'vendor_id',
        string='Commission Lines',
        help='Named external and internal commission beneficiaries with individual rates',
    )
    total_external_commission = fields.Monetary(
        string='External Commission',
        currency_field='currency_id',
        compute='_compute_commission', store=True,
        help='Total external commission payable to broker/agency (sum of Commission Lines).')
    total_internal_commission = fields.Monetary(
        string='Internal Commission',
        currency_field='currency_id',
        compute='_compute_commission', store=True,
        help='Total internal commission (sum of Commission Lines).')
    total_commission = fields.Monetary(
        string='Total Commission',
        currency_field='currency_id',
        compute='_compute_commission', store=True)
    commission_line_count = fields.Integer(
        string='Commission Line Count',
        compute='_compute_commission_line_count',
    )
    total_tax = fields.Monetary(
        string='Total Tax', currency_field='currency_id',
        compute='_compute_commission', store=True)
    amount_total = fields.Monetary(
        string='Total w/ Tax', currency_field='currency_id',
        compute='_compute_commission', store=True)

    # -------------------------------------------------------------------------
    # SALES CONSOLIDATION FIELDS
    # -------------------------------------------------------------------------
    sale_type = fields.Selection([
        ('off_plan', 'Off-Plan'),
        ('secondary', 'Secondary'),
    ], string='Sale Type', default='off_plan', tracking=True,
       help='Discriminator for sales consolidation: off-plan (new build) or secondary (resale).')

    payment_recorded = fields.Boolean(string='Payment Recorded', default=False, tracking=True,
                                       help='True when a payment has been recorded against this booking.')
    payment_amount = fields.Monetary(string='Payment Amount', currency_field='currency_id',
                                      tracking=True,
                                      help='Amount of payment recorded against this booking.')
    payment_date = fields.Date(string='Payment Date', tracking=True,
                                help='Date when payment was recorded.')
    sale_confirmed = fields.Boolean(string='Sale Confirmed', default=False, tracking=True,
                                     help='True when a sale.contract has been created and linked from this booking.')
    blocked_attempt_logged = fields.Boolean(string='Blocked Attempt Logged', default=False,
                                             help='True when a blocked confirm-sale attempt has been logged to audit.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('property.vendor') or _('New')
        return super(PropertyVendor, self).create(vals_list)

    @api.depends('commission_line_ids.commission_amount', 'commission_line_ids.category',
                 'commission_line_ids.amount_tax', 'commission_line_ids.amount_total')
    def _compute_commission(self):
        for rec in self:
            lines = rec.commission_line_ids
            rec.total_external_commission = sum(
                l.commission_amount for l in lines if l.category == 'external')
            rec.total_internal_commission = sum(
                l.commission_amount for l in lines if l.category == 'internal')
            rec.total_commission = sum(lines.mapped('commission_amount'))
            rec.total_tax = sum(lines.mapped('amount_tax'))
            rec.amount_total = sum(lines.mapped('amount_total'))

    @api.depends('commission_line_ids')
    def _compute_commission_line_count(self):
        # Non-stored display counter, split out of _compute_commission so the
        # stored monetary totals and this non-stored count are not produced by
        # one method (Odoo flags the differing compute_sudo/store defaults).
        for rec in self:
            rec.commission_line_count = len(rec.commission_line_ids)

    # -------------------------------------------------------------------------
    # State transitions
    # -------------------------------------------------------------------------
    def action_confirm(self):
        for rec in self:
            rec.state = 'confirmed'
            if rec.property_id:
                rec.property_id.state = 'booked'

    def action_cancel(self):
        for rec in self:
            rec.state = 'cancelled'
            if rec.property_id:
                rec.property_id.state = 'available'

    def action_draft(self):
        for rec in self:
            if rec.state != 'cancelled':
                raise UserError(_('Only cancelled bookings can be set back to draft. Cancel it first.'))
            rec.state = 'draft'

    # -------------------------------------------------------------------------
    # RECORD PAYMENT
    # -------------------------------------------------------------------------
    def action_record_payment(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Booking must be confirmed before recording payment.'))
        if self.payment_recorded:
            raise UserError(_('Payment has already been recorded for this booking.'))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.record.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_booking_id': self.id},
        }

    # -------------------------------------------------------------------------
    # CONFIRM SALE (with payment gate)
    # -------------------------------------------------------------------------
    def action_confirm_sale(self, acknowledgement=None):
        self.ensure_one()
        if self.sale_confirmed:
            raise UserError(_('Sale has already been confirmed for this booking.'))

        require_payment = self.env['ir.config_parameter'].sudo().get_param(
            'sgc_mt.confirm_sales_requires_payment', 'True') == 'True'

        if require_payment and not self.payment_recorded:
            if not self.blocked_attempt_logged:
                service = sgc_audit_internal_service.SgcAuditInternalService(self.env)
                service.capture_event(
                    tier='2',
                    operation='blocked_confirm_sale',
                    operation_label='Blocked Confirm Sale (hard gate)',
                    model='property.vendor',
                    res_id=self.id,
                    res_display_name=self.name,
                    reason='Payment not recorded. Hard gate is active.',
                    source='ui',
                    observed_fields=False,
                )
                self.blocked_attempt_logged = True
            raise UserError(_(
                'Payment must be recorded before confirming sale. '
                'Hard gate is active. Please record payment first.'
            ))

        if not self.payment_recorded and not require_payment:
            if not acknowledgement:
                raise UserError(_('Acknowledgement is required when confirming sale without payment in permissive mode.'))
            service = sgc_audit_internal_service.SgcAuditInternalService(self.env)
            service.capture_event(
                tier='1',
                operation='confirm_sale_permissive',
                operation_label='Confirm Sale (Permissive - No Payment)',
                model='property.vendor',
                res_id=self.id,
                res_display_name=self.name,
                reason=acknowledgement,
                source='ui',
                observed_fields=False,
            )
        elif self.payment_recorded:
            service = sgc_audit_internal_service.SgcAuditInternalService(self.env)
            service.capture_event(
                tier='2',
                operation='confirm_sale',
                operation_label='Confirm Sale (Hard Gate Passed)',
                model='property.vendor',
                res_id=self.id,
                res_display_name=self.name,
                reason='Payment recorded. Hard gate satisfied.',
                source='ui',
                observed_fields=False,
            )

        sale_contract_vals = {
            'property_id': self.property_id.id,
            'buyer_id': self.customer_id.id,
            'seller_id': self.vendor_id.id,
            'sale_price': self.sale_price,
            'currency_id': self.currency_id.id,
            'contract_date': fields.Date.today(),
            'booking_amount': self.payment_amount or 0.0,
            'notes': self.notes,
            'signed_via_portal': self.signed_via_portal,
            'state': 'draft',
            'company_id': self.company_id.id,
        }
        sale_contract = self.env['sale.contract'].create(sale_contract_vals)

        for commission_line in self.commission_line_ids:
            self.env['property.commission.line'].create({
                'contract_id': sale_contract.id,
                'partner_id': commission_line.partner_id.id,
                'category': commission_line.category,
                'role': commission_line.role,
                'custom_role_name': commission_line.custom_role_name,
                'computation_type': commission_line.computation_type,
                'commission_percentage': commission_line.commission_percentage,
                'commission_fixed_amount': commission_line.commission_fixed_amount,
                'commission_amount': commission_line.commission_amount,
                'tax_ids': [(6, 0, commission_line.tax_ids.ids)],
                'amount_tax': commission_line.amount_tax,
                'amount_total': commission_line.amount_total,
                'state': commission_line.state,
                'notes': commission_line.notes,
                'currency_id': commission_line.currency_id.id,
            })

        self.sale_contract_id = sale_contract.id
        self.sale_confirmed = True

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'property.vendor',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_confirm_sale_button(self):
        """Form-button entry point for 'Confirm Sales'.

        Hard gate ON or payment recorded: delegate to action_confirm_sale(),
        preserving the documented hard-gate UserError.
        Permissive mode with no payment: open the acknowledgement wizard, so
        the Tier-1 audited 'confirm_sale_permissive' path is reachable instead
        of dead-ending on 'Acknowledgement is required'.
        """
        self.ensure_one()
        require_payment = self.env['ir.config_parameter'].sudo().get_param(
            'sgc_mt.confirm_sales_requires_payment', 'True') == 'True'
        if require_payment or self.payment_recorded:
            return self.action_confirm_sale()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.confirm.warning.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_booking_id': self.id},
        }

    # -------------------------------------------------------------------------
    # REPORT: payment-plan rows for printable Sale documents
    # -------------------------------------------------------------------------
    def _report_offer_payment_plan_lines(self):
        """Payment-plan rows for the booking's printed Sales Offer.

        Priority:
          1. The payment plan selected on this booking (offer-level), projected
             from the schedule onto the booking Sale Price - no contract needed.
          2. Otherwise real generated installments from the linked contract.
          3. Otherwise the linked contract's schedule, projected.
        Returns [] when nothing is configured (report shows the fallback note).
        """
        self.ensure_one()
        contract = self.sale_contract_id
        schedule = self.payment_schedule_id or (
            contract.payment_schedule_id if contract else False)
        basis = self.sale_price or (contract.sale_price or 0.0)
        if contract and contract.installment_ids and not self.payment_schedule_id:
            return contract._report_payment_plan_lines()
        if not schedule or not basis:
            return []
        anchor = self.contract_date or self.date or fields.Date.today()
        return schedule._project_report_rows(basis, anchor)
