from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .property_details import CTX_RELEASE


class SaleContract(models.Model):
    """Contract stages. `state` is the CONTRACT lifecycle; the unit's own status lives on property.details."""
    _inherit = 'sale.contract'

    # Re-declared in full (order = lifecycle). Legacy keys draft / signed / completed / cancelled are kept with
    # their meaning: draft = SPA being drafted, signed = SPA signed, completed = handed over.
    state = fields.Selection(selection=[
        ('eoi', 'EOI'),
        ('booked', 'Booked'),
        ('confirmed', 'Confirmed'),
        ('draft', 'Draft'),
        ('spa_issued', 'SPA Issued'),
        ('signed', 'SPA Signed'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ])
    eoi_id = fields.Many2one('property.eoi', string='EOI', readonly=True, copy=False, index=True)
    booking_id = fields.Many2one('property.vendor', string='Booking', readonly=True, copy=False, index=True)
    unit_state = fields.Selection(related='property_id.state', string='Unit Status', readonly=True)

    # ------------------------------------------------------------------ transitions
    def _sgc_is_staged(self):
        self.ensure_one()
        return bool(self.eoi_id or self.booking_id)

    def _sgc_cancel_without_release(self):
        """Cancel the contract record only. The caller decides what happens to the unit."""
        self.filtered(lambda c: c.state not in ('completed', 'cancelled')).write({'state': 'cancelled'})

    def action_issue_spa(self):
        for contract in self:
            if contract.state not in ('confirmed', 'draft'):
                raise UserError(_('The SPA can only be issued once the sale is Confirmed (contract status: %s).',
                                  dict(contract._fields['state']._description_selection(self.env)).get(contract.state)))
            if contract._sgc_is_staged() and contract.property_id.state != 'confirmed_sale':
                raise UserError(_('The unit is not a Confirmed Sale, so the SPA cannot be issued.'))
            contract._assign_reference()
            contract.state = 'spa_issued'
            contract.message_post(body=_('SPA issued.'))

    def action_sign(self):
        staged = self.filtered(lambda c: c.state == 'spa_issued')
        early = self.filtered(lambda c: c.state in ('eoi', 'booked', 'confirmed'))
        if early:
            raise UserError(_('The SPA must be issued before it can be signed (contract status: %s).',
                              dict(early[0]._fields['state']._description_selection(self.env)).get(early[0].state)))
        for contract in staged:
            contract._assign_reference()
            contract.state = 'signed'
            contract.message_post(body=_('SPA signed.'))      # the unit stays a Confirmed Sale
        rest = self - staged
        return super(SaleContract, rest).action_sign() if rest else True

    def action_cancel(self):
        for contract in self:
            if contract.state in ('completed', 'cancelled'):
                raise UserError(_('Completed or already cancelled contracts cannot be cancelled.'))
            prop = contract.property_id
            protected = (prop.state in ('confirmed_sale', 'sold') or contract.state in ('confirmed', 'spa_issued') or
                         (contract.state == 'signed' and contract._sgc_is_staged()))
            if protected and not self.env.context.get(CTX_RELEASE):
                raise UserError(_('Contract %s is a Confirmed Sale. It cannot be cancelled here - open the booking '
                                  'and use "Cancel Confirmed Sale" (manager action, reason required).', contract.name))
            if contract.state == 'eoi':
                raise UserError(_('This contract belongs to an EOI. Cancel the EOI to release the unit.'))
            if contract.state == 'booked':
                raise UserError(_('This contract belongs to a booking. Cancel the booking to release the unit.'))
        return super().action_cancel()
