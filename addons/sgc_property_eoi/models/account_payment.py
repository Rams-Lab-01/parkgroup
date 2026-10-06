from odoo import fields, models


class AccountPayment(models.Model):
    """Inverse side of the EOI / booking payment links. Lets a security rule give sales officers read access
    to ONLY the payments that belong to an EOI or a booking, without opening the whole payment ledger."""
    _inherit = 'account.payment'

    sgc_eoi_ids = fields.Many2many('property.eoi', 'property_eoi_payment_rel', 'payment_id', 'eoi_id',
                                   string='EOIs', copy=False, readonly=True)
    sgc_booking_ids = fields.Many2many('property.vendor', 'property_vendor_payment_rel', 'payment_id',
                                       'booking_id', string='Bookings', copy=False, readonly=True)
