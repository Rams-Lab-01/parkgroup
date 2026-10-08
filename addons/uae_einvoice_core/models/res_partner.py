# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Party identification fields per runbook section 8.3.

    Legal registration ID + type (TL/EID/PAS/CD)   IBT-030/047, BTAE-15/16
    VAT/TRN identifier                             IBT-031/048
    Electronic address (= TRN, scheme 0235)        IBT-034/049
"""

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    legal_registration_id = fields.Char(
        string="Legal Registration ID",
        help="Trade License number, Emirates ID, Passport number, or "
             "Cabinet Decision reference, per legal_registration_type.",
    )
    legal_registration_type = fields.Selection(
        selection=[
            ("TL", "Trade License"),
            ("EID", "Emirates ID"),
            ("PAS", "Passport"),
            ("CD", "Cabinet Decision"),
        ],
        string="Legal Registration Type",
    )
    trn = fields.Char(
        string="Tax Registration Number (TRN)",
        help="UAE TRN. Also used as the electronic address identifier "
             "under scheme 0235 (peppol_scheme_id).",
    )
    peppol_scheme_id = fields.Char(
        string="Electronic Address Scheme",
        default="0235",
        help="Scheme ID for the electronic address. 0235 = UAE TRN scheme.",
    )
