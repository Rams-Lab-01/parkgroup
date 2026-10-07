"""Install-time migration for databases that already hold bookings and contracts.

Strategy (nothing is converted, nothing is deleted):
  * Existing units keep their status. A unit that is "Booked" stays Booked (the old Book / Hold *is* the new
    Booked stage - there was never an EOI concept to migrate). No unit is moved to EOI or Confirmed Sale.
  * Existing contracts keep their state (draft / signed / completed / cancelled) - all remain valid values.
  * Bookings whose payment was recorded by hand before this module are flagged `legacy_payment`: they stay
    "payment recorded" and keep passing the sales gate, but are not pretended to be backed by accounting.
"""
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    Vendor = env['property.vendor']
    legacy = Vendor.search([('payment_recorded', '=', True), ('payment_ids', '=', False)])
    if legacy:
        legacy.write({'legacy_payment': True})
        for booking in legacy:
            if not booking.booking_amount and booking.payment_amount:
                booking.booking_amount = booking.payment_amount
    _logger.info('sgc_property_eoi: %s legacy manual-payment bookings preserved, %s bookings total',
                 len(legacy), Vendor.search_count([]))
