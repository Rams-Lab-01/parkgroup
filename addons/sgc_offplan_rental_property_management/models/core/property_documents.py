# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class PropertyDocuments(models.Model):
    _name = 'property.documents'
    _description = 'Property Documents'
    _inherit = ['file.validation.mixin', 'sgc.critical.audit.mixin']
    _order = 'document_date desc, id desc'

    # Field-level allowlist: the fields carrying the ownership and approval
    # claims this record exists to assert.  The attachment payload and its file
    # name are deliberately out of scope, and the verification report states
    # exactly this list rather than implying the whole record is attested.
    _audit_watched_fields = frozenset({
        'property_id',
        'doc_type',
        'doc_category',
        'document_reference_number',
        'expiry_date',
        'approval_state',
        'ownership_verified',
        'verified_by',
        'verification_date',
        'portal_visible',
    })

    property_id = fields.Many2one('property.details', string='Property', required=True)
    document_date = fields.Date(string='Document Date')
    doc_type = fields.Many2one('certificate.type', string='Document Type')
    file_name = fields.Char(string='File Name')
    document = fields.Binary(string='Document', attachment=True)
    portal_visible = fields.Boolean(string='Visible on Portal', default=False)
    doc_category = fields.Selection([('lease', 'Lease'), ('certificate', 'Certificate'), ('inspection', 'Inspection'), ('invoice', 'Invoice'), ('id', 'ID Document'), ('form_a', 'Form A'), ('title_deed', 'Title Deed'), ('passport', 'Passport'), ('noc', 'NOC (No Objection Certificate)'), ('oqood', 'Oqood (Interim Property Register)'), ('trust_escrow', 'Trust/Escrow Account Statement'), ('rera_permit', 'RERA Permit'), ('ejari', 'Ejari Certificate'), ('valuation', 'Property Valuation'), ('spa', 'Sale Purchase Agreement'), ('other', 'Other')], string='Category', default='other')
    uploaded_by_partner_id = fields.Many2one('res.partner', string='Uploaded By')
    approval_state = fields.Selection([('n_a', 'N/A'), ('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], string='Approval Status', default='n_a')

    # --------------------------------------------------------------------------
    # COMPLIANCE TRACKING FIELDS
    # --------------------------------------------------------------------------
    expiry_date = fields.Date(string='Document Expiry Date',
        help="Date when this document expires (e.g., passport, visa, trade license)")
    ownership_verified = fields.Boolean(string='Ownership Verified',
        help="Document has been verified as proof of ownership")
    verified_by = fields.Many2one('res.users', string='Verified By')
    verification_date = fields.Datetime(string='Verification Date')
    document_reference_number = fields.Char(string='Reference Number',
        help="Document reference number (e.g., Title Deed number, passport number)")
    notes = fields.Text(string='Verification Notes')

    # --------------------------------------------------------------------------
    # COMPUTED EXPIRY FIELDS
    # --------------------------------------------------------------------------
    is_expired = fields.Boolean(compute='_compute_is_expired', string='Expired')
    days_until_expiry = fields.Integer(compute='_compute_is_expired', string='Days Until Expiry')

    # --------------------------------------------------------------------------
    # FILE TYPE (for the kanban preview — `document` can be any file type, not
    # just images, so the card needs to know whether it can render an <img>
    # preview or should fall back to a file-type icon instead).
    # --------------------------------------------------------------------------
    file_extension = fields.Char(compute='_compute_file_extension', string='File Extension')
    is_image_document = fields.Boolean(compute='_compute_file_extension', string='Is Image')

    @api.depends('file_name')
    def _compute_file_extension(self):
        image_extensions = ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp', 'svg')
        for rec in self:
            ext = rec.file_name.rsplit('.', 1)[-1].lower() if rec.file_name and '.' in rec.file_name else ''
            rec.file_extension = ext
            rec.is_image_document = ext in image_extensions

    @api.depends('expiry_date')
    def _compute_is_expired(self):
        today = fields.Date.today()
        for rec in self:
            if rec.expiry_date:
                rec.is_expired = rec.expiry_date < today
                delta = (rec.expiry_date - today).days
                rec.days_until_expiry = -1 if rec.is_expired else delta
            else:
                rec.is_expired = False
                rec.days_until_expiry = 0

    @api.onchange('doc_category')
    def _onchange_doc_category(self):
        compliance_types = ['form_a', 'title_deed', 'passport', 'noc', 'oqood']
        if self.doc_category in compliance_types:
            self.approval_state = 'n_a'

    @api.constrains('portal_visible', 'approval_state')
    def _check_approval_state_portal_visible(self):
        for rec in self:
            if rec.approval_state != 'n_a' and not rec.portal_visible:
                raise ValidationError(_("Approval status can only be set for documents that are visible on the portal."))
