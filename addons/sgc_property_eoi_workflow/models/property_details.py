# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

# The unit stages that may only be reached once money is actually posted.
PAYMENT_GATED_STATES = {'eoi': 'EOI', 'booked': 'Booked'}

class PropertyDetails(models.Model):
    _inherit = 'property.details'

    state = fields.Selection(
        selection_add=[
            ('eoi', 'Expression of Interest (EOI)'),
        ],
        ondelete={'eoi': 'set default'},
    )

    sale_contract_ids = fields.One2many(
        'sale.contract', 'property_id',
        string='Contracts', 
    )
    eoi_contract_ids = fields.One2many(
        'sale.contract', 'property_id',
        string='EOI Contracts',
        domain=[('state', '=', 'eoi')],
    )
    eoi_count = fields.Integer(
        string='EOI Count',
        compute='_compute_eoi_counts',
    )
    booking_contract_ids = fields.One2many(
        'sale.contract', 'property_id',
        string='Bookings',
        domain=[('state', '=', 'booked')],
    )
    booking_count = fields.Integer(
        string='Bookings Count',
        compute='_compute_eoi_counts',
    )

    # ------------------------------------------------------------------
    # Money gate: what has actually been received against this unit
    # ------------------------------------------------------------------
    eoi_received_amount = fields.Monetary(
        string='Received (Accounting)',
        currency_field='currency_id',
        compute='_compute_eoi_received',
        help='Posted customer receipts registered against this unit in Accounting.',
    )

    @api.depends('currency_id')
    def _compute_eoi_received(self):
        helper = self.env['sgc.eoi.receipt.helper']
        for rec in self:
            rec.eoi_received_amount = helper._received_for_unit(rec)

    def _sgc_eoi_receipts(self):
        """The posted customer receipts registered against this unit."""
        self.ensure_one()
        return self.env['sgc.eoi.receipt.helper']._receipts_for_unit(self)

    def write(self, vals):
        """A unit only enters the sale journey once a receipt is registered against it.

        Every caller goes through here, so the gate cannot be walked around by
        writing the state directly.
        """
        target = vals.get('state')
        if target in PAYMENT_GATED_STATES:
            for rec in self:
                if rec.state == target:
                    continue
                if not rec._sgc_eoi_receipts():
                    raise UserError(_(
                        'Unit %s cannot move to %s: no posted receipt is registered against it '
                        'in Accounting. Record the receipt (PDC, cash, bank transfer or any other '
                        'proof of payment) against the unit first.',
                        rec.display_name, PAYMENT_GATED_STATES[target]))
        return super().write(vals)

    @api.depends('sale_contract_ids.state')
    def _compute_eoi_counts(self):
        for prop in self:
            eoi_cnt = 0
            bk_cnt = 0
            for contract in prop.sale_contract_ids:
                if contract.state == 'eoi':
                    eoi_cnt += 1
                elif contract.state == 'booked':
                    bk_cnt += 1
            prop.eoi_count = eoi_cnt
            prop.booking_count = bk_cnt

    def action_open_eoi_wizard(self):
        self.ensure_one()
        if self.state not in ['available']:
            raise UserError(_('EOI can only be registered for Available properties.'))
        return {
            'name': _('Register Expression of Interest (EOI)'),
            'type': 'ir.actions.act_window',
            'res_model': 'eoi.registration.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_property_id': self.id,
                'default_sale_price': self.sale_price or self.price or 0.0,
                'default_seller_id': self.owner_id.id if self.owner_id else False,
            },
        }

    def action_open_booking_wizard(self):
        self.ensure_one()
        if self.state not in ['available', 'eoi']:
            raise UserError(_('Booking can only be created for properties in Available or EOI status.'))
        return {
            'name': _('Convert to Booking / Direct Booking'),
            'type': 'ir.actions.act_window',
            'res_model': 'eoi.to.booking.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_property_id': self.id,
                'default_sale_price': self.sale_price or self.price or 0.0,
            },
        }

    def action_convert_eoi_to_booked(self):
        self.ensure_one()
        active_eoi = self.sale_contract_ids.filtered(lambda c: c.state == 'eoi')
        if not active_eoi:
            return self.action_open_booking_wizard()
        contract = active_eoi[0]
        contract.action_convert_to_booked()
        return True

    def action_cancel_eoi(self):
        self.ensure_one()
        active_eoi = self.sale_contract_ids.filtered(lambda c: c.state == 'eoi')
        for contract in active_eoi:
            contract.action_cancel_refund_eoi()
        self.write({'state': 'available'})
        return True

    def action_view_eoi_contracts(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sgc_offplan_rental_property_management.action_sale_contract')
        action['domain'] = [('property_id', '=', self.id), ('state', '=', 'eoi')]
        action['context'] = {'default_property_id': self.id, 'default_state': 'eoi'}
        action['name'] = _('EOI Contracts - %s', self.name)
        return action

    def action_view_eoi_receipts(self):
        """The money registered against this unit in Accounting."""
        self.ensure_one()
        return {
            'name': _('Receipts - %s', self.name),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('property_id', '=', self.id)],
        }
