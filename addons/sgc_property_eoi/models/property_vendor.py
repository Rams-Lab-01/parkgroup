import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .property_details import CTX_RELEASE

_logger = logging.getLogger(__name__)
HARD_GATE_PARAM = 'sgc_mt.confirm_sales_requires_payment'


def _audit(env, **event):
    """Record through the base module's audit service when it is there (it is git-ignored in some checkouts)."""
    try:
        from odoo.addons.sgc_offplan_rental_property_management.services import sgc_audit_internal_service
        sgc_audit_internal_service.SgcAuditInternalService(env).capture_event(**event)
    except Exception:  # an audit outage must never block a sale, but it must be visible
        _logger.warning('Audit event %s could not be recorded', event.get('operation'), exc_info=True)


class PropertyVendor(models.Model):
    """The booking record (Book / Hold). Extended with the EOI link and an accounting-backed booking payment."""
    _inherit = 'property.vendor'

    eoi_id = fields.Many2one('property.eoi', string='EOI', readonly=True, copy=False, index=True)
    booking_amount = fields.Monetary(
        string='Booking Amount', currency_field='currency_id', compute='_compute_booking_amount',
        store=True, readonly=False, tracking=True,
        help='Amount the purchaser must pay for the booking to become a Confirmed Sale. Defaults to the unit '
             'price x its Booking %.')
    payment_ids = fields.Many2many('account.payment', 'property_vendor_payment_rel', 'booking_id', 'payment_id',
                                   string='Booking Payments', copy=False)
    booking_paid_amount = fields.Monetary(string='Amount Paid', currency_field='currency_id',
                                          compute='_compute_booking_payment')
    booking_outstanding = fields.Monetary(string='Outstanding', currency_field='currency_id',
                                          compute='_compute_booking_payment')
    booking_payment_state = fields.Selection([
        ('pending', 'Pending'), ('partial', 'Partially Paid'), ('paid', 'Paid'), ('confirmed', 'Confirmed'),
    ], string='Booking Payment', compute='_compute_booking_payment')
    payment_verified = fields.Boolean(string='Booking Payment Verified', compute='_compute_booking_payment')
    legacy_payment = fields.Boolean(
        string='Legacy Manual Payment', default=False, copy=False,
        help='Payment was recorded manually before accounting-backed payments existed. Kept valid, not re-verified.')

    # ------------------------------------------------------------------ computes
    @api.depends('property_id.booking_percentage', 'property_id.price', 'sale_price')
    def _compute_booking_amount(self):
        for rec in self:
            if not rec.booking_amount:
                basis = rec.sale_price or rec.property_id.sale_price or rec.property_id.price
                pct = rec.property_id.booking_percentage or 0.0
                rec.booking_amount = round(basis * pct / 100.0, 2) if basis and pct else rec.booking_amount

    @api.depends('payment_ids.state', 'payment_ids.amount', 'booking_amount', 'payment_recorded',
                 'payment_amount', 'sale_confirmed', 'legacy_payment', 'currency_id')
    def _compute_booking_payment(self):
        helper = self.env['sgc.payment.helper']
        for rec in self:
            currency = rec.currency_id or rec.company_id.currency_id
            if rec.payment_ids:
                paid = helper._counted_amount(rec.payment_ids, currency, rec.company_id)
                verified = rec.booking_amount > 0 and paid + 0.005 >= rec.booking_amount
            elif rec.payment_recorded and rec.legacy_payment:
                paid = rec.payment_amount or 0.0
                verified = True                       # grandfathered manual record
            else:
                paid, verified = 0.0, False
            rec.booking_paid_amount = paid
            rec.booking_outstanding = max(rec.booking_amount - paid, 0.0) if not rec.legacy_payment else 0.0
            rec.payment_verified = verified
            if verified and rec.sale_confirmed:
                rec.booking_payment_state = 'confirmed'
            elif verified:
                rec.booking_payment_state = 'paid'
            elif paid > 0:
                rec.booking_payment_state = 'partial'
            else:
                rec.booking_payment_state = 'pending'

    def _sgc_sync_payment_flags(self):
        """Keep the base module's stored flags (payment_recorded / amount / date) a pure reflection of the real
        accounting payments, so its existing hard gate keeps working but can no longer be satisfied by a manual
        tick. Legacy manual records are left alone."""
        for rec in self:
            if rec.legacy_payment and not rec.payment_ids:
                continue
            rec.invalidate_recordset(['booking_paid_amount', 'payment_verified'])
            counted = self.env['sgc.payment.helper']._counted_payments(rec.payment_ids)
            vals = {'payment_recorded': rec.payment_verified, 'payment_amount': rec.booking_paid_amount,
                    'payment_date': max(counted.mapped('date')) if counted else False}
            if any(rec[k] != v for k, v in vals.items()):
                rec.write(vals)

    # ------------------------------------------------------------------ unit rules
    def _sgc_check_unit_for_booking(self):
        for rec in self:
            prop = rec.property_id
            if not prop:
                continue
            if prop.state == 'available':
                continue
            if prop.state == 'eoi' and rec.eoi_id and prop.active_eoi_id == rec.eoi_id:
                continue
            if prop.state == 'booked' and rec.state == 'confirmed':
                continue
            raise UserError(_('%(unit)s is "%(state)s" and cannot be booked. Only an Available unit - or a unit '
                              'reserved by this booking\'s own EOI - can be booked.',
                              unit=prop.display_name, state=prop._sgc_state_label(prop.state)))

    # ------------------------------------------------------------------ workflow
    def action_confirm(self):
        self._sgc_check_unit_for_booking()
        res = super().action_confirm()
        for rec in self:
            contract = rec.sale_contract_id
            if contract and contract.state in ('eoi', 'draft') and contract.eoi_id:
                contract.write({'state': 'booked', 'booking_id': rec.id})
        return res

    def action_record_payment(self):
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Booking must be confirmed before recording payment.'))
        if self.sale_confirmed:
            raise UserError(_('The sale is already confirmed.'))
        if self.payment_verified:
            raise UserError(_('The booking payment is already complete and verified.'))
        return {
            'type': 'ir.actions.act_window', 'name': _('Record Booking Payment'),
            'res_model': 'sale.record.payment.wizard', 'view_mode': 'form', 'target': 'new',
            'context': {'default_booking_id': self.id,
                        'default_payment_amount': self.booking_outstanding or self.booking_amount},
        }

    def action_cancel(self):
        for rec in self:
            prop = rec.property_id
            if rec.sale_confirmed or prop.state in ('confirmed_sale', 'sold'):
                raise UserError(_('Booking %s is a Confirmed Sale. It cannot be cancelled here - use "Cancel '
                                  'Confirmed Sale" (manager action, reason required).', rec.name))
            if prop.state == 'eoi':
                raise UserError(_('The unit is held by an EOI, not by this booking; cancelling the booking must '
                                  'not release it. Cancel the EOI instead.'))
        res = super().action_cancel()
        for rec in self:
            contract = rec.sale_contract_id
            if contract and contract.state in ('eoi', 'booked'):
                contract._sgc_cancel_without_release()
        return res

    def action_confirm_sale(self, acknowledgement=None):
        """Booked -> Confirmed Sale. Only possible once the booking payment is verified (hard gate), or - in the
        base module's permissive mode - after an audited acknowledgement."""
        self.ensure_one()
        if self.state != 'confirmed':
            raise UserError(_('Confirm the booking first (status: %s).', self.state))
        self._sgc_sync_payment_flags()
        contract = self.sale_contract_id
        if not contract:
            # Legacy path (booking without an EOI contract): the base method creates the contract.
            res = super().action_confirm_sale(acknowledgement=acknowledgement)
            self.sale_contract_id.write({'state': 'confirmed', 'booking_id': self.id})
            self.property_id.write({'state': 'confirmed_sale'})
            return res
        if self.sale_confirmed:
            raise UserError(_('Sale has already been confirmed for this booking.'))
        require = self.env['ir.config_parameter'].sudo().get_param(HARD_GATE_PARAM, 'True') == 'True'
        if not self.payment_verified:
            if require:
                if not self.blocked_attempt_logged:
                    _audit(self.env, tier='2', operation='blocked_confirm_sale',
                           operation_label='Blocked Confirm Sale (hard gate)', model='property.vendor',
                           res_id=self.id, res_display_name=self.name,
                           reason='Booking payment not verified. Hard gate is active.', source='ui',
                           observed_fields=False)
                    self.blocked_attempt_logged = True
                raise UserError(_(
                    'The booking payment is not complete: paid %(paid)s of %(due)s (outstanding %(left)s). '
                    'Record or link the booking payment before confirming the sale.',
                    paid=self.booking_paid_amount, due=self.booking_amount, left=self.booking_outstanding))
            if not acknowledgement:
                raise UserError(_('Acknowledgement is required when confirming a sale without a verified payment.'))
            _audit(self.env, tier='1', operation='confirm_sale_permissive',
                   operation_label='Confirm Sale (Permissive - No Verified Payment)', model='property.vendor',
                   res_id=self.id, res_display_name=self.name, reason=acknowledgement, source='ui',
                   observed_fields=False)
        else:
            _audit(self.env, tier='2', operation='confirm_sale', operation_label='Confirm Sale (Hard Gate Passed)',
                   model='property.vendor', res_id=self.id, res_display_name=self.name,
                   reason='Booking payment verified against accounting. Hard gate satisfied.', source='ui',
                   observed_fields=False)
        contract.write({'state': 'confirmed', 'booking_id': self.id, 'booking_amount': self.booking_amount})
        self.sale_confirmed = True
        self.property_id.write({'state': 'confirmed_sale'})
        contract.message_post(body=_('Sale confirmed: booking payment %(paid)s of %(due)s received.',
                                     paid=self.booking_paid_amount, due=self.booking_amount))
        return {'type': 'ir.actions.act_window', 'res_model': 'property.vendor', 'res_id': self.id,
                'view_mode': 'form', 'target': 'current'}

    def action_open_cancel_confirmed_wizard(self):
        self.ensure_one()
        if not self.sale_confirmed:
            raise UserError(_('This booking is not a Confirmed Sale. Use the normal Cancel button.'))
        return {'type': 'ir.actions.act_window', 'name': _('Cancel Confirmed Sale'),
                'res_model': 'property.sale.cancel.wizard', 'view_mode': 'form', 'target': 'new',
                'context': {'default_booking_id': self.id}}

    def _sgc_cancel_confirmed_sale(self, reason):
        """The ONLY route that releases a confirmed unit. Payments are never touched - refunds are an
        accounting decision - but the amount paid is written to the audit trail."""
        self.ensure_one()
        if not self.env.user.has_group('sgc_offplan_rental_property_management.property_rental_manager'):
            raise UserError(_('Only a Property Manager can cancel a confirmed sale.'))
        if not (reason or '').strip():
            raise UserError(_('A cancellation reason is required.'))
        contract = self.sale_contract_id
        if contract and contract.state == 'completed':
            raise UserError(_('The contract is completed (handed over) and cannot be cancelled here.'))
        paid = self.booking_paid_amount
        self = self.with_context(**{CTX_RELEASE: True})
        if contract:
            contract.with_context(**{CTX_RELEASE: True}).write({'state': 'cancelled'})
        self.write({'state': 'cancelled', 'sale_confirmed': False})
        self.property_id.write({'state': 'available'})
        _audit(self.env, tier='2', operation='cancel_confirmed_sale', operation_label='Cancel Confirmed Sale',
               model='property.vendor', res_id=self.id, res_display_name=self.name,
               reason='%s | paid at cancellation: %s' % (reason, paid), source='ui', observed_fields=False)
        self.message_post(body=_('Confirmed sale cancelled by %(user)s. Reason: %(reason)s. Amount paid at '
                                 'cancellation: %(paid)s - handle any refund in Accounting.',
                                 user=self.env.user.name, reason=reason, paid=paid))
        return True

    # ------------------------------------------------------------------ reports
    def action_print_booking_confirmation(self):
        self.ensure_one()
        return self.env.ref('sgc_property_eoi.action_report_booking_confirmation').report_action(self)

    def _report_data(self):
        self.ensure_one()
        from .res_company import (DEFAULT_BOOKING_DOCS, DEFAULT_BOOKING_STEPS, DEFAULT_BOOKING_TERMS,
                                  DEFAULT_DOC_FOOTER)
        company = self.company_id
        lines = lambda txt: [ln.strip() for ln in (txt or '').splitlines() if ln.strip()]
        seller = self.eoi_id._seller_partner() if self.eoi_id else (
            self.property_id.project_id.developer_id or self.vendor_id or company.partner_id)
        basis = self.sale_price or self.property_id.sale_price or self.property_id.price
        fees = [(label, amt) for label, amt in (
            (_('Registration Fee'), self.property_id.registration_fee), (_('Admin Fee'), self.property_id.admin_fee))
            if amt]
        return {
            'seller': seller,
            'price': basis,
            'fees': fees,
            'terms': lines(company.sgc_booking_terms or DEFAULT_BOOKING_TERMS),
            'steps': lines(company.sgc_booking_next_steps or DEFAULT_BOOKING_STEPS),
            'documents': lines(company.sgc_booking_documents or DEFAULT_BOOKING_DOCS),
            'footer': company.sgc_doc_footer or DEFAULT_DOC_FOOTER,
        }
