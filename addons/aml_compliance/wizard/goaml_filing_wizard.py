# -*- coding: utf-8 -*-
"""
goAML End-to-End Self-Filing Wizards

GoAMLFilingWizard  — Step-by-step wizard for the MLRO to:
  1. Run a preflight checklist on the report data
  2. Generate the goAML-compliant XML in one click
  3. Download the XML and upload it manually to the UAE FIU goAML portal
  4. Record the filing and optional FIU reference to complete the workflow

GoAMLAcknowledgementWizard — Lightweight wizard for MLRO to record
  the FIU reference number and acknowledgement date once the FIU
  responds to the filed report.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class GoAMLFilingWizard(models.TransientModel):
    """MLRO end-to-end goAML self-filing wizard."""

    _name = 'aml.goaml.filing.wizard'
    _description = 'goAML Self-Filing Wizard'

    # ----------------------------------------------------------------
    # Core relation
    # ----------------------------------------------------------------

    report_id = fields.Many2one(
        'aml.goaml.report',
        string='Report',
        required=True,
        readonly=True,
        ondelete='cascade',
    )

    # ----------------------------------------------------------------
    # Summary display (related, read-only)
    # ----------------------------------------------------------------

    report_type = fields.Selection(
        related='report_id.report_type',
        string='Report Type',
        readonly=True,
    )
    report_name = fields.Char(
        related='report_id.name',
        string='Reference',
        readonly=True,
    )
    report_state = fields.Selection(
        related='report_id.state',
        string='Current State',
        readonly=True,
    )
    partner_name = fields.Char(
        string='Subject',
        compute='_compute_display_fields',
    )

    # ----------------------------------------------------------------
    # Preflight checklist (computed)
    # ----------------------------------------------------------------

    check_subject = fields.Boolean(
        string='Subject (Customer)',
        compute='_compute_checklist',
    )
    check_identifier = fields.Boolean(
        string='Customer Identifier',
        compute='_compute_checklist',
    )
    check_report_type = fields.Boolean(
        string='Report Type Selected',
        compute='_compute_checklist',
    )
    check_suspicion = fields.Boolean(
        string='Reason for Suspicion',
        compute='_compute_checklist',
    )
    check_transaction = fields.Boolean(
        string='Transaction Details',
        compute='_compute_checklist',
    )
    checklist_passed = fields.Boolean(
        string='All Checks Passed',
        compute='_compute_checklist',
    )
    checklist_issues = fields.Text(
        string='Outstanding Issues',
        compute='_compute_checklist',
        help='Lists incomplete fields that must be fixed before generating XML.',
    )

    # ----------------------------------------------------------------
    # XML artefact (related/computed)
    # ----------------------------------------------------------------

    xml_generated = fields.Boolean(
        string='XML Generated',
        compute='_compute_xml_generated',
    )
    xml_file = fields.Binary(
        string='goAML XML File',
        related='report_id.xml_file',
        readonly=True,
    )
    xml_filename = fields.Char(
        related='report_id.xml_filename',
        readonly=True,
    )

    # ----------------------------------------------------------------
    # Filing confirmation
    # ----------------------------------------------------------------

    filing_date = fields.Date(
        string='Filing Date',
        default=fields.Date.today,
        required=True,
        help='The date on which the XML was uploaded to the goAML portal.',
    )
    fiu_reference = fields.Char(
        string='FIU Reference (Optional)',
        help=(
            'Reference number received from the UAE FIU goAML portal immediately '
            'after upload. This can also be entered later via "Record FIU Acknowledgement".'
        ),
    )
    mlro_notes = fields.Text(
        string='MLRO Filing Notes',
        help='Internal notes about this filing for audit trail purposes.',
    )

    # ----------------------------------------------------------------
    # Computed helpers
    # ----------------------------------------------------------------

    @api.depends('report_id.partner_id')
    def _compute_display_fields(self):
        for rec in self:
            rec.partner_name = rec.report_id.partner_id.name if rec.report_id else ''

    @api.depends(
        'report_id',
        'report_id.partner_id',
        'report_id.report_type',
        'report_id.reason_for_suspicion',
        'report_id.transaction_amount',
        'report_id.transaction_date',
        'report_id.transaction_type',
    )
    def _compute_checklist(self):
        for rec in self:
            r = rec.report_id
            if not r:
                rec.check_subject = rec.check_identifier = False
                rec.check_report_type = rec.check_suspicion = False
                rec.check_transaction = rec.checklist_passed = False
                rec.checklist_issues = ''
                continue

            partner = r.partner_id
            rec.check_subject = bool(partner)

            rec.check_identifier = bool(
                partner and (
                    partner.vat
                    or (hasattr(partner, 'x_passport_number') and partner.x_passport_number)
                    or (hasattr(partner, 'x_emirates_id') and partner.x_emirates_id)
                )
            )

            rec.check_report_type = bool(r.report_type)

            if r.report_type in ('str', 'sar'):
                rec.check_suspicion = bool(r.reason_for_suspicion)
            else:
                rec.check_suspicion = True  # Not required for CTR

            if r.report_type == 'str':
                rec.check_transaction = bool(r.transaction_amount and r.transaction_date)
            elif r.report_type == 'ctr':
                rec.check_transaction = bool(
                    r.transaction_amount
                    and r.transaction_date
                    and r.transaction_type == 'cash'
                )
            else:
                rec.check_transaction = True  # SAR — no transaction required

            rec.checklist_passed = all([
                rec.check_subject,
                rec.check_identifier,
                rec.check_report_type,
                rec.check_suspicion,
                rec.check_transaction,
            ])

            issues = []
            if not rec.check_subject:
                issues.append('• Subject (customer) is not set on the report.')
            if not rec.check_identifier:
                issues.append(
                    '• Customer has no identifier. Add VAT, Passport Number, or Emirates ID.'
                )
            if not rec.check_report_type:
                issues.append('• Report type (STR / SAR / CTR) is not selected.')
            if not rec.check_suspicion:
                issues.append('• Reason for Suspicion is required for STR/SAR reports.')
            if not rec.check_transaction:
                issues.append(
                    '• Transaction amount, date, or type (cash) is incomplete.'
                )

            rec.checklist_issues = '\n'.join(issues) if issues else 'All preflight checks passed ✓'

    @api.depends('report_id.xml_file')
    def _compute_xml_generated(self):
        for rec in self:
            rec.xml_generated = bool(rec.report_id and rec.report_id.xml_file)

    # ----------------------------------------------------------------
    # Button actions
    # ----------------------------------------------------------------

    def action_generate_xml(self):
        """
        Advance report through workflow if needed, then generate XML.
        The MLRO can do this in one click from draft state — the wizard
        internally moves the report to 'approved' before generating.
        """
        self.ensure_one()
        if not self.env.user.has_group('aml_compliance.group_mlro'):
            raise UserError(_('Only the MLRO can generate the goAML XML for filing.'))
        if not self.checklist_passed:
            raise UserError(
                _('Cannot generate XML. Fix the following issues first:\n\n%s',
                  self.checklist_issues)
            )

        report = self.report_id

        # Auto-advance: draft → submitted → approved so XML generation is allowed
        if report.state == 'draft':
            report._validate_report_requirements()
            report.write({'state': 'submitted'})

        if report.state == 'submitted':
            report.write({
                'state': 'approved',
                'mlro_id': self.env.uid,
                'mlro_review_date': fields.Datetime.now(),
            })

        # Generate the XML file (state is now 'approved')
        report.action_generate_xml()

        # Re-open the same wizard so the user sees the updated state
        return {
            'type': 'ir.actions.act_window',
            'name': _('File goAML Report'),
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_confirm_filing(self):
        """
        Mark the report as filed, record filing metadata, and sync
        any linked transaction alerts to 'str_filed' state.
        """
        self.ensure_one()
        if not self.env.user.has_group('aml_compliance.group_mlro'):
            raise UserError(_('Only the MLRO can confirm goAML filing.'))
        if not self.checklist_passed:
            raise UserError(_('Report is incomplete. Fix checklist issues first.'))
        if not self.xml_generated:
            raise UserError(
                _('Generate and download the goAML XML file before confirming filing.')
            )

        report = self.report_id

        if report.state == 'filed':
            raise UserError(_('This report has already been filed.'))
        if report.state != 'approved':
            raise UserError(
                _('Report must be in Approved state to be filed. '
                  'Use "Generate XML" button first (it advances the state automatically).')
            )

        if report.state == 'approved':
            write_vals = {
                'state': 'filed',
                'filed_by_id': self.env.uid,
                'filing_date': fields.Datetime.now(),
            }
            if self.fiu_reference:
                write_vals['fiu_reference'] = self.fiu_reference
            if self.mlro_notes:
                write_vals['mlro_notes'] = self.mlro_notes

            report.write(write_vals)

            # Sync linked transaction alerts
            linked_alerts = self.env['aml.transaction.alert'].search([
                ('goaml_report_id', '=', report.id),
            ])
            if linked_alerts:
                linked_alerts.write({
                    'state': 'str_filed',
                    'resolution_date': fields.Datetime.now(),
                })

            # Audit trail message
            note_parts = [
                '<b>goAML Report filed with UAE FIU</b>',
                f'Filed by: {self.env.user.name}',
                f'Filing date: {self.filing_date}',
            ]
            if self.fiu_reference:
                note_parts.append(f'FIU Reference: {self.fiu_reference}')
            if self.mlro_notes:
                note_parts.append(f'Notes: {self.mlro_notes}')

            report.message_post(
                body='<br/>'.join(note_parts),
                message_type='notification',
            )

        return {'type': 'ir.actions.act_window_close'}


class GoAMLAcknowledgementWizard(models.TransientModel):
    """
    Record the FIU acknowledgement after the filed report has been
    processed by the UAE Financial Intelligence Unit.
    """

    _name = 'aml.goaml.acknowledgement.wizard'
    _description = 'goAML FIU Acknowledgement Wizard'

    report_id = fields.Many2one(
        'aml.goaml.report',
        string='Report',
        required=True,
        readonly=True,
        ondelete='cascade',
    )
    report_name = fields.Char(
        related='report_id.name',
        readonly=True,
    )
    report_type = fields.Selection(
        related='report_id.report_type',
        readonly=True,
    )

    fiu_reference = fields.Char(
        string='FIU Reference Number',
        required=True,
        help='The reference number assigned by the UAE FIU upon processing.',
    )
    acknowledgement_date = fields.Date(
        string='FIU Acknowledgement Date',
        required=True,
        default=fields.Date.today,
    )
    fiu_response_notes = fields.Text(
        string='FIU Response Notes',
        help='Any feedback, queries, or notes received from the FIU.',
    )

    def action_confirm_acknowledgement(self):
        """Mark report as acknowledged and record the FIU response."""
        self.ensure_one()
        if not self.env.user.has_group('aml_compliance.group_mlro'):
            raise UserError(_('Only the MLRO can record FIU acknowledgements.'))

        report = self.report_id
        if report.state != 'filed':
            raise UserError(_('Only reports in "Filed with FIU" state can be acknowledged.'))

        report.write({
            'state': 'acknowledged',
            'fiu_reference': self.fiu_reference,
            'fiu_acknowledgement_date': self.acknowledgement_date,
        })

        note_parts = [
            '<b>FIU Acknowledgement Recorded</b>',
            f'FIU Reference: {self.fiu_reference}',
            f'Acknowledgement Date: {self.acknowledgement_date}',
        ]
        if self.fiu_response_notes:
            note_parts.append(f'FIU Notes: {self.fiu_response_notes}')

        report.message_post(
            body='<br/>'.join(note_parts),
            message_type='notification',
        )
        return {'type': 'ir.actions.act_window_close'}
