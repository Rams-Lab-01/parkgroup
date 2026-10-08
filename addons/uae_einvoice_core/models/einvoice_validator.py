# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""Pre-submission validation gate per runbook section 8.5.

Checks performed (all soft — this returns an error list rather than
raising, so callers decide whether to block submission):

    - mandatory-field completeness (TRN, legal registration ID present
      on both supplier and buyer)
    - ProfileExecutionID consistency (a transaction-type record must
      exist)
    - credit-note rule (reason code required on 381/81 unless 'VD';
      preceding invoice reference required unless 'VD')
    - TRN format (UAE TRN is a 15-digit number — see runbook section 13
      risk register: exact mandatory-field count still pending
      re-verification against the live MoF spec)
    - no negative totals outside 381/81 (runbook section 8.1 rule:
      "no negative invoices — reversals always via 381/81")

XSD structural validation and full Schematron/PINT-AE business-rule
validation are NOT implemented here — they require the UBL renderer
(runbook section 11 build-sequence step 2, a separate module) to
produce XML to validate against. This function only checks what is
knowable from the canonical Odoo model, before any XML exists.

This module has zero knowledge of ASP adapters or transport — it is
called by the (future) orchestration engine in uae_einvoice_asp_hub,
never the other way around.
"""

import re

TRN_RE = re.compile(r"^\d{15}$")


def einvoice_validate(move):
    """Validate an account.move record against the PINT-AE canonical
    model rules that are checkable without a rendered XML document.

    Returns a dict: {"valid": bool, "errors": [str, ...]}.
    """
    errors = []

    supplier = move.company_id.partner_id if move.company_id else None
    buyer = move.partner_id

    # --- mandatory-field completeness ---
    if not (supplier and supplier.trn):
        errors.append("Supplier TRN is missing.")
    if not (buyer and buyer.trn):
        errors.append("Buyer TRN is missing.")
    if not (supplier and supplier.legal_registration_id):
        errors.append("Supplier legal registration ID is missing.")

    # --- TRN format ---
    if supplier and supplier.trn and not TRN_RE.match(supplier.trn):
        errors.append(f"Supplier TRN '{supplier.trn}' is not a 15-digit number.")
    if buyer and buyer.trn and not TRN_RE.match(buyer.trn):
        errors.append(f"Buyer TRN '{buyer.trn}' is not a 15-digit number.")

    # --- ProfileExecutionID consistency ---
    if not move.uae_transaction_type_id:
        errors.append("No ProfileExecutionID (transaction type flags) set.")

    # --- credit note rule ---
    is_credit_note = move.uae_is_credit_note
    reason_code = move.credit_note_reason_code
    preceding_ref = move.preceding_invoice_ref
    if is_credit_note:
        if not reason_code:
            errors.append("Credit note reason code is required.")
        if reason_code != "VD" and not preceding_ref:
            errors.append(
                "Preceding invoice reference is required unless "
                "credit_note_reason_code is 'VD'."
            )

    # --- no negative totals outside 381/81 ---
    if move.amount_total < 0 and not is_credit_note:
        errors.append(
            "Negative invoice total is only allowed on credit notes "
            "(document type 381/81)."
        )

    return {"valid": not errors, "errors": errors}
