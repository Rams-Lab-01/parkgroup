from odoo import fields, models

DEFAULT_EOI_NOTICE = (
    "This document records an Expression of Interest (EOI) and an initial, temporary reservation of the unit "
    "named above. It is NOT a booking, a confirmed sale or an agreement for sale and purchase, and it does not "
    "transfer any right, title or interest in the unit.")

DEFAULT_EOI_TERMS = """The Purchaser is interested in the Project and wishes to reserve the unit described in this EOI before a formal booking is opened. The EOI Amount, if any, is paid in the manner stated above.
The Seller will invite the Purchaser to sign the Booking Form when bookings open. The Purchaser agrees to sign it on the Seller's standard terms and payment plan; the EOI Amount will then be allocated towards the purchase price.
If the Purchaser cancels this EOI, or does not sign the Booking Form within the period notified by the Seller, the Seller may cancel the EOI and release the unit. Treatment of the EOI Amount follows the terms agreed in writing with the Purchaser.
The Seller may cancel this EOI at any time before the Booking Form is signed. If the Seller cancels, any EOI Amount received is returned to the Purchaser without interest within the period stated in the Seller's terms.
This EOI is personal to the Purchaser and may not be assigned or transferred.
This EOI is governed by the laws of the Emirate in which the Project is located and the applicable federal laws of the United Arab Emirates."""

DEFAULT_BOOKING_TERMS = """The unit is reserved for the Purchaser only once the Booking Amount has been received in cleared funds by the Seller.
The Booking Amount is credited towards the purchase price. This document is a booking confirmation; it is not a Sale and Purchase Agreement.
The sale becomes a Confirmed Sale only after the Booking Amount has been paid in full and verified by the Seller's finance team.
If the Purchaser does not complete the required payment within the period notified by the Seller, the Seller may cancel the booking and release the unit in accordance with the agreed terms.
The Sale and Purchase Agreement will be issued after the sale is confirmed and must be signed by the Purchaser within the period it states."""

DEFAULT_BOOKING_STEPS = """Settle any outstanding Booking Amount to confirm the sale.
Provide the required identification and corporate documents.
Review and sign the Sale and Purchase Agreement (SPA) once it is issued.
Follow the payment plan milestones stated in the SPA."""

DEFAULT_BOOKING_DOCS = """Valid passport copy of the Purchaser and any joint Purchaser.
UAE residents: valid Emirates ID and visa page.
Companies: trade licence, memorandum of association, authorised signatory passport and authorising document.
Power of Attorney, where applicable, attested as required by UAE regulations."""

DEFAULT_DOC_FOOTER = "Confidential - prepared for the named Purchaser only. Not valid without authorised signature."


class ResCompany(models.Model):
    _inherit = 'res.company'

    sgc_eoi_notice = fields.Text(string='EOI Important Notice', translate=True,
                                 help='Shown prominently on the EOI. Leave empty to use the standard wording.')
    sgc_eoi_terms = fields.Text(string='EOI Terms and Conditions', translate=True,
                                help='One clause per line. Leave empty to use the standard wording.')
    sgc_booking_terms = fields.Text(string='Booking Confirmation Terms', translate=True,
                                    help='One clause per line.')
    sgc_booking_next_steps = fields.Text(string='Booking: Next Steps', translate=True, help='One step per line.')
    sgc_booking_documents = fields.Text(string='Booking: Required Documents', translate=True,
                                        help='One item per line.')
    sgc_doc_footer = fields.Char(string='Document Footer Notice', translate=True)
    sgc_eoi_validity_days = fields.Integer(
        string='Default EOI Validity (days)', default=14,
        help='Used to propose the expiry date of a new EOI. 0 = no expiry proposed.')
