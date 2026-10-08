# -*- coding: utf-8 -*-
"""
Investigation Case Management

Groups related transaction alerts into structured investigation cases
for compliance officers and MLRO review.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AMLInvestigationCase(models.Model):
    """Investigation case grouping related transaction monitoring alerts"""

    _name = 'aml.investigation.case'
    _description = 'Investigation Case'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'create_date desc'

    name = fields.Char(
        string='Case Reference',
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )

    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        ondelete='set null',
        index=True,
        tracking=True,
    )

    state = fields.Selection([
        ('open', 'Open'),
        ('investigating', 'Under Investigation'),
        ('escalated', 'Escalated to MLRO'),
        ('closed', 'Closed'),
        ('str_filed', 'STR Filed'),
    ], string='Status', default='open', tracking=True, index=True)

    alert_ids = fields.One2many(
        'aml.transaction.alert',
        'case_id',
        string='Linked Alerts',
    )

    alert_count = fields.Integer(
        string='# Alerts',
        compute='_compute_alert_count',
    )

    severity = fields.Selection(
        selection=[
            ('low', 'Low'),
            ('medium', 'Medium'),
            ('high', 'High'),
            ('critical', 'Critical'),
        ],
        compute='_compute_severity',
        string='Severity',
        store=True,
    )

    assigned_to_id = fields.Many2one(
        'res.users',
        string='Assigned To',
        tracking=True,
    )

    investigation_notes = fields.Text(
        string='Investigation Notes',
    )

    resolution_summary = fields.Text(
        string='Resolution Summary',
    )

    resolution_date = fields.Datetime(
        string='Resolution Date',
        readonly=True,
    )

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

    def _compute_alert_count(self):
        for rec in self:
            rec.alert_count = len(rec.alert_ids)

    @api.depends('alert_ids.severity')
    def _compute_severity(self):
        for rec in self:
            severities = rec.alert_ids.mapped('severity')
            if 'critical' in severities:
                rec.severity = 'critical'
            elif 'high' in severities:
                rec.severity = 'high'
            elif 'medium' in severities:
                rec.severity = 'medium'
            else:
                rec.severity = 'low'

    # -------------------------------------------------------
    # SEQUENCE
    # -------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'aml.investigation.case'
                ) or 'New'
        return super().create(vals_list)

    # -------------------------------------------------------
    # WORKFLOW ACTIONS
    # -------------------------------------------------------

    def action_investigate(self):
        for rec in self:
            rec.write({
                'state': 'investigating',
                'assigned_to_id': rec.assigned_to_id.id or self.env.uid,
            })

    def action_escalate(self):
        for rec in self:
            rec.write({'state': 'escalated'})
            rec.message_post(
                body=_('Case escalated to MLRO for review.'),
                message_type='notification',
            )

    def action_close(self, summary=None):
        for rec in self:
            rec.write({
                'state': 'closed',
                'resolution_summary': summary or rec.resolution_summary,
                'resolution_date': fields.Datetime.now(),
            })

    def action_create_str(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('A customer must be linked to create an STR.'))
        report = self.env['aml.goaml.report'].create({
            'report_type': 'str',
            'partner_id': self.partner_id.id,
            'reason_for_suspicion': _(
                'Investigation Case %s\nAlerts: %s\nNotes: %s',
                self.name,
                ', '.join(self.alert_ids.mapped('name')),
                self.resolution_summary or '',
            ),
        })
        self.write({
            'state': 'str_filed',
            'goaml_report_id': report.id,
        })
        self.alert_ids.write({'goaml_report_id': report.id})

    goaml_report_id = fields.Many2one(
        'aml.goaml.report',
        string='Related goAML Report',
        ondelete='set null',
    )

    # -------------------------------------------------------
    # BUTTON: Create case from alerts
    # -------------------------------------------------------

    @api.model
    def create_from_alerts(self, alert_ids):
        """Create an investigation case from selected alerts."""
        alerts = self.env['aml.transaction.alert'].browse(alert_ids)
        partners = alerts.mapped('partner_id')
        if len(partners) > 1:
            raise UserError(_(
                'Selected alerts belong to different customers. '
                'Please select alerts for the same customer.'
            ))
        case = self.create({
            'partner_id': partners.id if partners else False,
            'alert_ids': [(6, 0, alert_ids)],
        })
        alerts.write({'case_id': case.id})
        return case
