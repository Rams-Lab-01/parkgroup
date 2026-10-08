# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""PINT-AE document type codes per runbook section 8.1.

Codes:
    380  Tax Invoice
    381  Tax Credit Note
    480  Invoice, out of tax scope
    81   Credit note, out of tax scope
"""

from odoo import fields, models


class UAEInvoiceDocumentType(models.Model):
    _name = "uae.einvoice.document.type"
    _description = "PINT-AE Document Type Code"

    code = fields.Char(required=True, size=3, index=True)
    name = fields.Char(required=True, translate=True)
    is_credit_note = fields.Boolean(
        string="Credit Note",
        help="True for 381 / 81. Used by the validator to enforce the\n"
             "'no negative invoices' rule (runbook section 8.1).",
    )
