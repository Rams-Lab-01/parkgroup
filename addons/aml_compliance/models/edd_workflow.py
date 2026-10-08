# -*- coding: utf-8 -*-
"""
Enhanced Due Diligence (EDD) Workflow

Structured EDD process triggered when a risk assessment classifies a
customer as High or Very High risk. Provides questionnaires, document
collection, and review workflow per CBUAE / FATF RBA guidance.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AMLEnquiryType(models.Model):
    """Enquiry types for EDD — e.g. Source of Funds, Business Nature"""

    _name = 'aml.edd.enquiry.type'
    _description = 'EDD Enquiry Type'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    required = fields.Boolean(
        string='Mandatory',
        help='This enquiry is mandatory and must be completed before EDD can be closed.',
    )


class AMLEnquiryResponse(models.Model):
    """Individual Q&A response within an EDD workflow"""

    _name = 'aml.edd.enquiry.response'
    _description = 'EDD Enquiry Response'
    _order = 'enquiry_type_id, create_date'

    workflow_id = fields.Many2one(
        'aml.edd.workflow',
        string='EDD Workflow',
        required=True,
        ondelete='cascade',
        index=True,
    )

    enquiry_type_id = fields.Many2one(
        'aml.edd.enquiry.type',
        string='Enquiry Type',
        required=True,
        ondelete='restrict',
    )

    question = fields.Char(
        string='Question',
        required=True,
    )

    response = fields.Text(
        string='Response',
    )

    attachment_ids = fields.One2many(
        'ir.attachment',
        compute='_compute_attachments',
        string='Supporting Documents',
        readonly=True,
    )

    completed = fields.Boolean(string='Completed', default=False)
    completed_by_id = fields.Many2one('res.users', string='Completed By', readonly=True)
    completed_date = fields.Datetime(string='Completed Date', readonly=True)

    def action_complete(self):
        for rec in self:
            rec.write({
                'completed': True,
                'completed_by_id': self.env.user.id,
                'completed_date': fields.Datetime.now(),
            })

    def _compute_attachments(self):
        for rec in self:
            rec.attachment_ids = self.env['ir.attachment'].search([
                ('res_model', '=', 'aml.edd.enquiry.response'),
                ('res_id', '=', rec.id),
            ])


class AMLEnquiryDocument(models.Model):
    """Document uploaded as part of EDD"""
    _name = 'aml.edd.document'
    _description = 'EDD Supporting Document'
    _order = 'create_date desc'

    workflow_id = fields.Many2one(
        'aml.edd.workflow',
        string='EDD Workflow',
        required=True,
        ondelete='cascade',
        index=True,
    )

    name = fields.Char(string='Document Name', required=True)
    document_type = fields.Selection([
        ('id_proof', 'Identity Proof'),
        ('address_proof', 'Address Proof'),
        ('source_funds', 'Source of Funds Evidence'),
        ('source_wealth', 'Source of Wealth Evidence'),
        ('bank_statement', 'Bank Statement'),
        ('business_registration', 'Business Registration'),
        ('financial_statement', 'Financial Statement'),
        ('other', 'Other'),
    ], string='Document Type', required=True, default='other')

    file = fields.Binary(string='File', attachment=True, required=True)
    filename = fields.Char(string='Filename')
    state = fields.Selection([
        ('pending', 'Pending Review'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ], string='Status', default='pending')

    verified_by_id = fields.Many2one('res.users', string='Verified By', readonly=True)
    verification_notes = fields.Text(string='Verification Notes')


class AMLEnquiryWorkflow(models.Model):
    """Enhanced Due Diligence (EDD) Workflow"""

    _name = 'aml.edd.workflow'
    _description = 'Enhanced Due Diligence Workflow'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'create_date desc'

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
    )

    assessment_id = fields.Many2one(
        'aml.risk.assessment',
        string='Source Risk Assessment',
        ondelete='set null',
        tracking=True,
    )

    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('review', 'Under Review'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True, index=True)

    # --- Workflow details ---
    assigned_to_id = fields.Many2one(
        'res.users',
        string='Assigned To',
        tracking=True,
    )

    start_date = fields.Datetime(
        string='Start Date',
        default=fields.Datetime.now,
        tracking=True,
    )

    due_date = fields.Date(
        string='Due Date',
        help='Target completion date for EDD',
    )

    completed_date = fields.Datetime(
        string='Completed Date',
        readonly=True,
    )

    # --- Enquiry responses ---
    enquiry_response_ids = fields.One2many(
        'aml.edd.enquiry.response',
        'workflow_id',
        string='Enquiry Responses',
    )

    enquiry_count = fields.Integer(
        string='# Enquiries',
        compute='_compute_enquiry_count',
    )

    completed_enquiry_count = fields.Integer(
        compute='_compute_enquiry_count',
        string='Completed',
    )

    # --- Documents ---
    document_ids = fields.One2many(
        'aml.edd.document',
        'workflow_id',
        string='Supporting Documents',
    )

    document_count = fields.Integer(
        string='# Documents',
        compute='_compute_document_count',
    )

    # --- Notes ---
    officer_notes = fields.Text(string='Officer Notes')

    conclusion = fields.Selection([
        ('satisfactory', 'Satisfactory — No Further Action'),
        ('enhanced_monitoring', 'Satisfactory — Enhanced Monitoring Required'),
        ('unsatisfactory', 'Unsatisfactory — Consider Exit / STR'),
    ], string='EDD Conclusion', tracking=True)

    conclusion_notes = fields.Text(string='Conclusion Notes')

    # --- Company ---
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    # -------------------------------------------------------
    # COMPUTED FIELDS
    # -------------------------------------------------------

    def _compute_enquiry_count(self):
        for rec in self:
            responses = rec.enquiry_response_ids
            rec.enquiry_count = len(responses)
            rec.completed_enquiry_count = len(responses.filtered('completed'))

    def _compute_document_count(self):
        for rec in self:
            rec.document_count = len(rec.document_ids)

    # -------------------------------------------------------
    # SEQUENCE
    # -------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'aml.edd.workflow'
                ) or 'New'
        return super().create(vals_list)

    # -------------------------------------------------------
    # WORKFLOW ACTIONS
    # -------------------------------------------------------

    def action_start(self):
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft EDD workflows can be started.'))
            rec.write({
                'state': 'in_progress',
                'start_date': fields.Datetime.now(),
            })
            rec._create_standard_enquiries()

    def action_submit_review(self):
        for rec in self:
            if rec.state != 'in_progress':
                raise UserError(_('Only in-progress EDD can be submitted for review.'))
            rec.write({'state': 'review'})

    def action_complete(self):
        for rec in self:
            if rec.state != 'review':
                raise UserError(_('EDD must be under review before completing.'))
            if not rec.conclusion:
                raise UserError(_('An EDD conclusion must be set before completing.'))
            rec.write({
                'state': 'completed',
                'completed_date': fields.Datetime.now(),
            })

    def action_cancel(self):
        for rec in self:
            if rec.state == 'completed':
                raise UserError(_('Cannot cancel a completed EDD workflow.'))
            rec.write({
                'state': 'cancelled',
            })

    def _create_standard_enquiries(self):
        """Create standard enquiry responses based on configured types."""
        EnquiryType = self.env['aml.edd.enquiry.type']
        types = EnquiryType.search([('active', '=', True)])
        if not types:
            _logger.info('No EDD enquiry types configured — using defaults.')
            # Create standard ones
            defaults = [
                ('SOURCE_FUNDS', 'Source of Funds — Explain the origin of funds for this engagement'),
                ('SOURCE_WEALTH', 'Source of Wealth — Explain how total wealth was accumulated'),
                ('BUSINESS_NATURE', 'Nature of Business — Describe the customer\'s business activities'),
                ('EXPECTED_ACTIVITY', 'Expected Account Activity — Describe expected transaction patterns'),
                ('COUNTRY_RISK', 'Country Risk — Explain any high-risk jurisdiction connections'),
                ('PEP_CLARIFICATION', 'PEP Relationship — Provide details on political exposure'),
            ]
            for code, question in defaults:
                existing = EnquiryType.search([('code', '=', code)], limit=1)
                if not existing:
                    existing = EnquiryType.create({
                        'name': question.split(' — ')[0],
                        'code': code,
                        'required': True,
                    })
                types |= existing

        for etype in types:
            self.env['aml.edd.enquiry.response'].create({
                'workflow_id': self.id,
                'enquiry_type_id': etype.id,
                'question': etype.name,
            })
