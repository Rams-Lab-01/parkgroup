# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Predefined generic endpoint IDs per runbook section 8.2 routing override.

These are the special-cased recipients that the PINT-AE spec uses when
the real counterparty cannot or should not be identified (deemed supply,
unregistered exports, out-of-scope buyer). Scheme is always '0235' and
the identifier is one of 9900000097/98/99.
"""

from odoo import fields, models


class UAEInvoiceEndpoint(models.Model):
    _name = "uae.einvoice.endpoint"
    _description = "PINT-AE Predefined Generic Endpoint"

    scheme_id = fields.Char(
        required=True, size=4, default="0235",
        help="Electronic address scheme. Always 0235 (UAE TRN) for these.",
    )
    identifier = fields.Char(required=True, size=15, index=True)
    purpose = fields.Selection(
        selection=[
            ("deemed_supply", "Deemed Supply"),
            ("out_of_scope_buyer", "Out-of-scope Buyer"),
            ("unregistered_exports", "Unregistered Exports"),
        ],
        required=True,
        help="Which routing-override scenario this endpoint is for.",
    )
