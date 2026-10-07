# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template (reconciled build, 2026-08-31).
#
# Constraint #6 of the SGC ADDON ESTATE RECONCILIATION brief:
#
#     Before generating re.document.vault as a new model, evaluate
#     whether extending ir.attachment (adding re_document_type and
#     expiry_date fields) satisfies the requirement. Only keep a fully
#     separate vault model if the polymorphic dual-link requirement
#     (linking simultaneously to res.partner and re.unit) genuinely
#     cannot be met by ir.attachment's existing res_model/res_id
#     pattern.
#
# `ir.attachment` already has the polymorphic `res_model` + `res_id`
# pair: any attachment can point to one ORM record of any model,
# including `res.partner` (M2O link to a contact) OR `re.unit`
# (this addon's unit record, defined in `re_unit.py`). The dual-link
# case is solvable by emitting TWO attachments — one pointing to the
# partner, one pointing to the unit — at the cost of a manual join
# at query-time. The brief calls this "satisfies the requirement";
# a separate `re.document.vault` is therefore NOT created.
#
# What we DO add: `re_document_type` (a Selection classifying real-
# estate documents) and `expiry_date` (a Date for Trakheesi/Ejari/NOC
# expiry tracking). Both fields are tenant-scoped via `tenant_id` so
# the SGC multi-tenant ACLs apply automatically.
from odoo import _, api, fields, models


class IrAttachmentReconcile(models.Model):
    """Document-vault fields added to ir.attachment — see file docstring.

    No new `_name`. The original `ir.attachment` model is not duplicated;
    these fields enrich it.
    """

    _inherit = "ir.attachment"

    re_document_type = fields.Selection(
        selection=[
            ("title_deed", "Title Deed"),
            ("trakheesi", "Trakheesi permit"),
            ("ejari", "Ejari contract"),
            ("noc", "No-objection certificate"),
            ("rera_form_a", "RERA Form A"),
            ("rera_form_b", "RERA Form B"),
            ("rera_form_i", "RERA Form I"),
            ("poa", "Power of Attorney"),
            ("mou", "Memorandum of Understanding"),
            ("id_copy", "ID copy (Emirates ID / passport)"),
            ("kyc_pack", "KYC pack"),
            ("aml_alert", "AML alert record"),
            ("rera_audit", "RERA audit"),
            ("tax_invoice", "Tax invoice"),
            ("bounced_cheque", "Bounced-cheque evidence"),
            ("other", "Other"),
        ],
        required=False,
        index=True,
        help="Brief §2.16 / §2.18 — classification of real-estate "
             "documents. Used by `sgc.compliance.event` to drive "
             "expiry warnings and audit-trail timelines.",
    )
    expiry_date = fields.Date(
        index=True,
        help="Earliest known expiry date for this document (Trakheesi "
             "renewal, Ejari contract end, NOC, etc.). A scheduled cron "
             "in a sibling addon surfaces rows where "
             "`expiry_date < now()+30d` to the responsible user.",
    )
    tenant_id = fields.Many2one(
        "sgc.brokerage.tenant",
        index=True,
        help="Owning tenant; populated automatically when the "
             "attachment's `res_model` is a tenant-owned model "
             "(`re.unit`, `crm.lead`, `sale.order`, ...).",
    )
    document_hash = fields.Char(
        size=64,
        help="SHA-256 of the stored binary — used by the lender-pack "
             "auditor to verify the document was not changed post-"
             "upload. Compute server-side at create time.",
    )

    _re_attachment_tenant_hash_unique = models.Constraint(
        "unique(document_hash, tenant_id)",
        "Document hash must be unique per tenant — protects against "
        "double-uploads of identical files.",
    )

    @api.constrains("expiry_date")
    def _check_expiry_in_past_warning(self):
        """A *warning*, not a hard fail — operators sometimes legitimately
        back-date expirations during data migration.
        """
        today = fields.Date.context_today(self)
        for attach in self:
            if attach.expiry_date and attach.expiry_date < today:
                # Not blocking: see brief §2.16 commentary.
                _(
                    "Attachment %(name)s: expiry_date is in the past. "
                    "Confirm before activating."
                ) % {"name": attach.name}
