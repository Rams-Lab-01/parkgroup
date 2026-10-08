# -*- coding: utf-8 -*-
"""
goAML Suspicious Transaction Report (STR) / Suspicious Activity Report (SAR)
Cash Transaction Report (CTR)

Generates goAML-compliant XML for filing with the UAE Financial
Intelligence Unit (FIU) via the goAML portal.

Report Types per CBUAE:
  - STR: Suspicious Transaction Report
  - SAR: Suspicious Activity Report (no transaction yet)
  - CTR: Cash Transaction Report (AED 55,000+ threshold)

XML Schema: goAML 4.0 (UAE FIU variant)
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from datetime import datetime
import logging
import xml.etree.ElementTree as ET
from xml.dom import minidom

_logger = logging.getLogger(__name__)

CTR_THRESHOLD_AED = 55000.0


class GoAMLReport(models.Model):
    """goAML report — STR, SAR, or CTR"""

    _name = 'aml.goaml.report'
    _description = 'goAML Report'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'report_date desc'

    name = fields.Char(
        string='Report Reference',
        required=True,
        readonly=True,
        default='New',
        copy=False,
        tracking=True,
    )

    report_type = fields.Selection([
        ('str', 'STR — Suspicious Transaction Report'),
        ('sar', 'SAR — Suspicious Activity Report'),
        ('ctr', 'CTR — Cash Transaction Report'),
    ], string='Report Type', required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted to MLRO'),
        ('approved', 'Approved by MLRO'),
        ('filed', 'Filed with FIU'),
        ('acknowledged', 'Acknowledged by FIU'),
        ('rejected', 'Rejected'),
    ], string='Status', default='draft', tracking=True, index=True)

    # --- Subject ---
    partner_id = fields.Many2one(
        'res.partner',
        string='Subject (Customer)',
        required=True,
        ondelete='restrict',
        tracking=True,
    )

    risk_assessment_id = fields.Many2one(
        'aml.risk.assessment',
        string='Related Risk Assessment',
        ondelete='set null',
    )

    # --- Report Details ---
    report_date = fields.Date(
        string='Report Date',
        default=fields.Date.today,
        required=True,
        tracking=True,
    )

    suspicion_date = fields.Date(
        string='Date Suspicion Arose',
        tracking=True,
    )

    reason_for_suspicion = fields.Text(
        string='Reason for Suspicion',
        help='Detailed description of why this transaction/activity is suspicious',
        tracking=True,
    )

    # --- Transaction Details ---
    transaction_date = fields.Date(
        string='Transaction Date',
        tracking=True,
    )

    transaction_amount = fields.Monetary(
        string='Transaction Amount (AED)',
        currency_field='currency_id',
        tracking=True,
    )

    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )

    transaction_type = fields.Selection([
        ('cash', 'Cash'),
        ('wire', 'Wire Transfer'),
        ('cheque', 'Cheque'),
        ('property', 'Property Transaction'),
        ('other', 'Other'),
    ], string='Transaction Type')

    transaction_description = fields.Text(
        string='Transaction Description',
    )

    related_invoice_ids = fields.Many2many(
        'account.move',
        'aml_goaml_report_invoice_rel',
        'report_id', 'invoice_id',
        string='Related Invoices',
        domain="[('partner_id', '=', partner_id), ('state', '=', 'posted')]",
    )

    # --- Involved Parties ---
    involved_party_ids = fields.One2many(
        'aml.goaml.involved.party',
        'report_id',
        string='Involved Parties',
    )

    # --- Filing ---
    filed_by_id = fields.Many2one(
        'res.users',
        string='Filed By',
        tracking=True,
    )

    filing_date = fields.Datetime(
        string='Filing Date',
        tracking=True,
    )

    fiu_reference = fields.Char(
        string='FIU Reference Number',
        tracking=True,
        help='Reference number assigned by the FIU upon acknowledgement',
    )

    fiu_acknowledgement_date = fields.Date(
        string='FIU Acknowledgement Date',
    )

    xml_file = fields.Binary(
        string='goAML XML File',
        attachment=True,
    )

    xml_filename = fields.Char(
        string='XML Filename',
    )

    # --- MLRO Review ---
    mlro_id = fields.Many2one(
        'res.users',
        string='MLRO',
        tracking=True,
    )

    mlro_review_date = fields.Datetime(
        string='MLRO Review Date',
    )

    mlro_notes = fields.Text(
        string='MLRO Notes',
    )

    linked_alert_count = fields.Integer(
        string='# Linked Alerts',
        compute='_compute_linked_alert_count',
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    # -------------------------------------------------------
    # CRUD
    # -------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                rtype = vals.get('report_type', 'str').upper()
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'aml.goaml.report'
                ) or 'New'
        return super().create(vals_list)

    # -------------------------------------------------------
    # WORKFLOW ACTIONS
    # -------------------------------------------------------

    @api.constrains('transaction_amount')
    def _check_transaction_amount(self):
        for rec in self:
            if rec.transaction_amount is not False and rec.transaction_amount is not None and rec.transaction_amount < 0:
                raise ValidationError(_('Transaction amount cannot be negative.'))

    def _validate_report_requirements(self):
        """Validate mandatory data by report type before submission or XML generation."""
        self.ensure_one()

        if self.report_type in ('str', 'sar') and not self.reason_for_suspicion:
            raise ValidationError(_('Reason for suspicion is required for STR/SAR reports.'))

        if self.report_type == 'str':
            if not self.transaction_amount:
                raise ValidationError(_('Transaction amount is required for STR reports.'))
            if not self.transaction_date:
                raise ValidationError(_('Transaction date is required for STR reports.'))

        if self.report_type == 'ctr':
            if not self.transaction_amount:
                raise ValidationError(_('Transaction amount is required for CTR reports.'))
            if self.transaction_amount < CTR_THRESHOLD_AED:
                raise ValidationError(
                    _('CTR amount must be at least AED %.2f.', CTR_THRESHOLD_AED)
                )
            if self.transaction_type != 'cash':
                raise ValidationError(_('CTR reports must use transaction type Cash.'))
            if not self.transaction_date:
                raise ValidationError(_('Transaction date is required for CTR reports.'))

        if self.report_type == 'sar' and self.transaction_amount:
            raise ValidationError(_('SAR reports should not include transaction amounts. Use STR or CTR instead.'))

        partner = self.partner_id
        has_identifier = bool(
            partner.vat
            or (hasattr(partner, 'x_passport_number') and partner.x_passport_number)
            or (hasattr(partner, 'x_emirates_id') and partner.x_emirates_id)
        )
        if not has_identifier:
            raise ValidationError(
                _('Customer identifier is missing. Please provide VAT, Passport Number, or Emirates ID before filing.')
            )

    def action_submit_to_mlro(self):
        """Submit report to MLRO for review"""
        if not self.env.user.has_group('aml_compliance.group_aml_officer'):
            raise UserError(_('Only AML Officers can submit goAML reports.'))
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Only draft reports can be submitted.'))
            rec._validate_report_requirements()
            rec.write({'state': 'submitted'})

    def action_mlro_approve(self):
        """MLRO approves the report for filing"""
        if not self.env.user.has_group('aml_compliance.group_mlro'):
            raise UserError(_('Only MLRO can approve goAML reports.'))
        for rec in self:
            if rec.state != 'submitted':
                raise UserError(_('Only submitted reports can be approved.'))
            rec.write({
                'state': 'approved',
                'mlro_id': self.env.uid,
                'mlro_review_date': fields.Datetime.now(),
            })

    def action_generate_xml(self):
        """Generate goAML-compliant XML and attach to record"""
        import base64
        for rec in self:
            if rec.state not in ('submitted', 'approved', 'filed', 'acknowledged'):
                raise UserError(_('XML generation is allowed only after submission to MLRO.'))

            rec._validate_report_requirements()
            xml_content = rec._build_goaml_xml()
            pretty_xml = minidom.parseString(
                ET.tostring(xml_content, encoding='unicode')
            ).toprettyxml(indent='  ', encoding='UTF-8')

            filename = (
                f"goAML_{rec.report_type.upper()}_"
                f"{rec.name.replace('/', '_')}_"
                f"{fields.Datetime.now().strftime('%Y%m%d_%H%M%S')}.xml"
            )
            rec.write({
                'xml_file': base64.b64encode(pretty_xml),
                'xml_filename': filename,
            })
            rec.message_post(
                body=_('goAML XML file generated: %s', filename),
                message_type='notification',
            )

    def action_mark_filed(self):
        """Mark report as filed with FIU"""
        if not self.env.user.has_group('aml_compliance.group_mlro'):
            raise UserError(_('Only MLRO can mark goAML reports as filed.'))
        for rec in self:
            if rec.state != 'approved':
                raise UserError(_('Only MLRO-approved reports can be filed.'))
            if not rec.xml_file:
                raise UserError(_('Generate the goAML XML file first.'))
            rec.write({
                'state': 'filed',
                'filed_by_id': self.env.uid,
                'filing_date': fields.Datetime.now(),
            })
            linked_alerts = self.env['aml.transaction.alert'].search([
                ('goaml_report_id', '=', rec.id),
            ])
            if linked_alerts:
                linked_alerts.write({
                    'state': 'str_filed',
                    'resolution_date': fields.Datetime.now(),
                })

    def action_mark_acknowledged(self):
        """Mark as acknowledged by FIU"""
        if not self.env.user.has_group('aml_compliance.group_mlro'):
            raise UserError(_('Only MLRO can acknowledge FIU filings.'))
        for rec in self:
            if rec.state != 'filed':
                raise UserError(_('Only filed reports can be acknowledged.'))
            rec.write({'state': 'acknowledged'})

    def action_reject(self):
        """MLRO rejects the report"""
        if not self.env.user.has_group('aml_compliance.group_mlro'):
            raise UserError(_('Only MLRO can reject goAML reports.'))
        for rec in self:
            rec.write({'state': 'rejected'})

    def action_reset_draft(self):
        for rec in self:
            rec.write({'state': 'draft'})

    def action_open_filing_wizard(self):
        """Open the MLRO end-to-end self-filing wizard."""
        self.ensure_one()
        if not self.env.user.has_group('aml_compliance.group_mlro'):
            raise UserError(_('Only the MLRO can access the goAML filing wizard.'))
        if self.state in ('filed', 'acknowledged'):
            raise UserError(_('This report has already been filed.'))
        wizard = self.env['aml.goaml.filing.wizard'].create({
            'report_id': self.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('File goAML Report — Self-Filing Wizard'),
            'res_model': 'aml.goaml.filing.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_acknowledgement_wizard(self):
        """Open wizard to record FIU reference and acknowledgement date."""
        self.ensure_one()
        if not self.env.user.has_group('aml_compliance.group_mlro'):
            raise UserError(_('Only the MLRO can record FIU acknowledgements.'))
        if self.state != 'filed':
            raise UserError(_('Only reports in "Filed with FIU" state can be acknowledged.'))
        wizard = self.env['aml.goaml.acknowledgement.wizard'].create({
            'report_id': self.id,
            'fiu_reference': self.fiu_reference or '',
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record FIU Acknowledgement'),
            'res_model': 'aml.goaml.acknowledgement.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _compute_linked_alert_count(self):
        for rec in self:
            rec.linked_alert_count = self.env['aml.transaction.alert'].search_count([
                ('goaml_report_id', '=', rec.id),
            ])

    def action_view_linked_alerts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Linked Alerts'),
            'res_model': 'aml.transaction.alert',
            'view_mode': 'list,form',
            'domain': [('goaml_report_id', '=', self.id)],
            'context': {'default_goaml_report_id': self.id},
        }

    # -------------------------------------------------------
    # goAML XML BUILDER
    # -------------------------------------------------------

    def _build_goaml_xml(self):
        """Build goAML 4.0 compliant XML structure.
        Schema: UAE FIU goAML variant.
        """
        self.ensure_one()
        root = ET.Element('goAMLReport')
        root.set('xmlns', 'http://www.un.org/goAML')
        root.set('version', '4.0')

        # Report Header
        header = ET.SubElement(root, 'report')
        ET.SubElement(header, 'report_code').text = self.report_type.upper()
        ET.SubElement(header, 'report_date').text = str(self.report_date)
        ET.SubElement(header, 'submission_date').text = str(fields.Date.today())
        ET.SubElement(header, 'currency_code').text = self.currency_id.name or 'AED'
        ET.SubElement(header, 'reporting_entity_id').text = str(self.company_id.id)

        # Reporting Entity
        entity = ET.SubElement(header, 'reporting_entity')
        ET.SubElement(entity, 'entity_name').text = self.company_id.name or ''
        ET.SubElement(entity, 'entity_address').text = self._get_company_address()
        if self.company_id.vat:
            ET.SubElement(entity, 'entity_registration_number').text = self.company_id.vat

        # Reported Person
        person = ET.SubElement(header, 'reported_person')
        partner = self.partner_id
        if partner.is_company:
            ET.SubElement(person, 'person_type').text = 'L'  # Legal
            ET.SubElement(person, 'entity_name').text = partner.name or ''
            if partner.vat:
                ET.SubElement(person, 'registration_number').text = partner.vat
        else:
            ET.SubElement(person, 'person_type').text = 'N'  # Natural
            ET.SubElement(person, 'first_name').text = (partner.name or '').split(' ')[0]
            ET.SubElement(person, 'last_name').text = ' '.join((partner.name or '').split(' ')[1:]) or partner.name or ''

        if partner.country_id:
            ET.SubElement(person, 'nationality').text = partner.country_id.code or ''
        if hasattr(partner, 'x_passport_number') and partner.x_passport_number:
            id_doc = ET.SubElement(person, 'identification')
            ET.SubElement(id_doc, 'id_type').text = 'P'  # Passport
            ET.SubElement(id_doc, 'id_number').text = partner.x_passport_number
        if hasattr(partner, 'x_emirates_id') and partner.x_emirates_id:
            id_doc = ET.SubElement(person, 'identification')
            ET.SubElement(id_doc, 'id_type').text = 'E'  # Emirates ID
            ET.SubElement(id_doc, 'id_number').text = partner.x_emirates_id

        # Address
        if partner.street or partner.city:
            addr = ET.SubElement(person, 'address')
            if partner.street:
                ET.SubElement(addr, 'address_line').text = partner.street
            if partner.city:
                ET.SubElement(addr, 'city').text = partner.city
            if partner.country_id:
                ET.SubElement(addr, 'country').text = partner.country_id.code or ''

        # Transaction (if applicable)
        if self.transaction_amount:
            txn = ET.SubElement(header, 'transaction')
            ET.SubElement(txn, 'transaction_date').text = str(self.transaction_date or self.report_date)
            ET.SubElement(txn, 'amount').text = str(self.transaction_amount)
            ET.SubElement(txn, 'currency').text = self.currency_id.name or 'AED'
            ET.SubElement(txn, 'transaction_type').text = self.transaction_type or 'other'
            if self.transaction_description:
                ET.SubElement(txn, 'description').text = self.transaction_description

        # Involved Parties
        for party in self.involved_party_ids:
            ip = ET.SubElement(header, 'involved_party')
            ET.SubElement(ip, 'party_name').text = party.name or ''
            ET.SubElement(ip, 'party_role').text = party.role or ''
            if party.country_id:
                ET.SubElement(ip, 'country').text = party.country_id.code or ''
            if party.id_number:
                ET.SubElement(ip, 'id_number').text = party.id_number

        # Suspicion Details
        if self.reason_for_suspicion:
            suspicion = ET.SubElement(header, 'suspicion')
            if self.suspicion_date:
                ET.SubElement(suspicion, 'date_suspicion').text = str(self.suspicion_date)
            ET.SubElement(suspicion, 'grounds_for_suspicion').text = self.reason_for_suspicion

        return root

    def _get_company_address(self):
        """Build company address string"""
        parts = filter(None, [
            self.company_id.street,
            self.company_id.city,
            self.company_id.state_id.name if self.company_id.state_id else None,
            self.company_id.country_id.name if self.company_id.country_id else None,
        ])
        return ', '.join(parts) or ''


class GoAMLInvolvedParty(models.Model):
    """Additional involved party in a goAML report"""

    _name = 'aml.goaml.involved.party'
    _description = 'goAML Involved Party'
    _order = 'role, name'

    report_id = fields.Many2one(
        'aml.goaml.report',
        string='Report',
        required=True,
        ondelete='cascade',
    )

    name = fields.Char(string='Party Name', required=True)

    role = fields.Selection([
        ('beneficiary', 'Beneficiary'),
        ('conductor', 'Transaction Conductor'),
        ('agent', 'Agent / Broker'),
        ('third_party', 'Third Party'),
    ], string='Role', required=True, default='beneficiary')

    partner_id = fields.Many2one(
        'res.partner',
        string='Linked Contact',
        ondelete='set null',
    )

    country_id = fields.Many2one(
        'res.country',
        string='Nationality',
    )

    id_type = fields.Selection([
        ('passport', 'Passport'),
        ('emirates_id', 'Emirates ID'),
        ('trade_license', 'Trade License'),
        ('other', 'Other'),
    ], string='ID Type')

    id_number = fields.Char(string='ID Number')
    notes = fields.Text(string='Notes')
