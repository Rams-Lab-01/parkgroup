# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Canonical PINT-AE invoice fields per runbook sections 4 and 8.

Layer 3 model only — this file has zero knowledge of ASP adapters,
transport clients, or the setup wizard (those live in uae_einvoice_asp_hub,
a separate module built in a later step).
"""

from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    uae_transaction_type_id = fields.Many2one(
        "uae.einvoice.transaction.type",
        string="PINT-AE Transaction Type Flags",
        help="8-bit ProfileExecutionID flag engine record for this invoice.",
    )
    transaction_type_flags = fields.Integer(
        string="ProfileExecutionID",
        related="uae_transaction_type_id.profile_execution_id",
        store=True,
        readonly=True,
    )

    uae_document_type_id = fields.Many2one(
        "uae.einvoice.document.type",
        string="PINT-AE Document Type",
        help="380 Tax Invoice / 381 Tax Credit Note / 480 out-of-scope "
             "invoice / 81 out-of-scope credit note (runbook section 8.1).",
    )
    credit_note_reason_code = fields.Char(
        string="Credit Note Reason Code",
        help="Mandatory for credit notes (381/81) per BTAE-03, except when "
             "the value itself is 'VD' (see runbook section 13 risk "
             "register — exact mandatory-field semantics pending "
             "re-verification against the live MoF spec).",
    )
    preceding_invoice_ref = fields.Char(
        string="Preceding Invoice Reference",
        help="IBG-03. Required on credit notes unless "
             "credit_note_reason_code == 'VD'.",
    )

    einvoice_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("validated", "Validated"),
            ("submitted_to_asp", "Submitted to ASP"),
            ("asp_validated", "ASP Validated"),
            ("asp_rejected", "ASP Rejected"),
            ("delivered_to_buyer", "Delivered to Buyer"),
            ("buyer_confirmed", "Buyer Confirmed"),
            ("fta_reported", "FTA Reported"),
        ],
        string="E-Invoice Status",
        default="draft",
        copy=False,
        help="Normalized status enum per runbook section 4/7. Transitions "
             "past 'validated' are driven by uae_einvoice_asp_hub in a "
             "later module — this field only stores the current state.",
    )

    uae_is_credit_note = fields.Boolean(
        compute="_compute_uae_is_credit_note",
        store=True,
        string="Is PINT-AE Credit Note",
    )

    @api.depends("uae_document_type_id")
    def _compute_uae_is_credit_note(self):
        for move in self:
            move.uae_is_credit_note = bool(
                move.uae_document_type_id and move.uae_document_type_id.is_credit_note
            )
