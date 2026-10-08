# -*- coding: utf-8 -*-
"""
Extend res.partner with AML risk fields.
These fields are updated when a risk assessment is approved.
"""

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class ResPartnerAML(models.Model):
    _inherit = 'res.partner'

    aml_risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('very_high', 'Very High'),
    ], string='AML Risk Level', tracking=True,
       help='Current AML risk classification based on latest approved assessment')

    aml_last_assessment_date = fields.Datetime(
        string='Last Risk Assessment',
        readonly=True,
    )

    aml_next_review_date = fields.Date(
        string='Next AML Review',
        readonly=True,
        tracking=True,
    )

    aml_risk_assessment_ids = fields.One2many(
        'aml.risk.assessment',
        'partner_id',
        string='Risk Assessments',
    )

    aml_risk_assessment_count = fields.Integer(
        string='# AML Assessments',
        compute='_compute_aml_risk_assessment_count',
    )

    aml_requires_edd = fields.Boolean(
        string='Requires EDD',
        compute='_compute_aml_requires_edd',
        store=True,
        help='Customer requires Enhanced Due Diligence',
    )

    # --- Sanctions screening fields ---
    aml_sanctions_match = fields.Boolean(
        string='Sanctions Match',
        tracking=True,
        help='Partner has a confirmed sanctions list match',
    )

    aml_last_screening_date = fields.Datetime(
        string='Last Sanctions Screening',
        readonly=True,
    )

    aml_screening_result_ids = fields.One2many(
        'aml.screening.result',
        'partner_id',
        string='Screening Results',
    )

    aml_screening_count = fields.Integer(
        string='# Screenings',
        compute='_compute_aml_screening_count',
    )

    # --- goAML report fields ---
    aml_goaml_report_ids = fields.One2many(
        'aml.goaml.report',
        'partner_id',
        string='goAML Reports',
    )

    aml_goaml_report_count = fields.Integer(
        string='# goAML Reports',
        compute='_compute_aml_goaml_report_count',
    )

    # --- Alert fields ---
    aml_alert_ids = fields.One2many(
        'aml.transaction.alert',
        'partner_id',
        string='Transaction Alerts',
    )

    aml_alert_count = fields.Integer(
        string='# Alerts',
        compute='_compute_aml_alert_count',
    )

    def _compute_aml_risk_assessment_count(self):
        for rec in self:
            rec.aml_risk_assessment_count = len(rec.aml_risk_assessment_ids)

    @api.depends('aml_risk_level')
    def _compute_aml_requires_edd(self):
        for rec in self:
            rec.aml_requires_edd = rec.aml_risk_level in ('high', 'very_high')

    def _compute_aml_screening_count(self):
        for rec in self:
            rec.aml_screening_count = len(rec.aml_screening_result_ids)

    def _compute_aml_goaml_report_count(self):
        for rec in self:
            rec.aml_goaml_report_count = len(rec.aml_goaml_report_ids)

    def _compute_aml_alert_count(self):
        for rec in self:
            rec.aml_alert_count = len(rec.aml_alert_ids)

    def action_view_risk_assessments(self):
        """View all risk assessments for this partner"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Risk Assessments'),
            'res_model': 'aml.risk.assessment',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_run_risk_assessment(self):
        """Quick action to create and run a risk assessment"""
        self.ensure_one()
        assessment = self.env['aml.risk.assessment'].create({
            'partner_id': self.id,
            'assessment_type': 'manual',
        })
        assessment.action_compute_risk()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Risk Assessment'),
            'res_model': 'aml.risk.assessment',
            'res_id': assessment.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_run_sanctions_screening(self):
        """Run sanctions screening against this partner"""
        self.ensure_one()
        results = self.env['aml.screening.result'].screen_partner(self)
        if results:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Screening Results'),
                'res_model': 'aml.screening.result',
                'view_mode': 'list,form',
                'domain': [('id', 'in', results.ids)],
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Screening Complete'),
                'message': _('No sanctions matches found.'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_view_screening_results(self):
        """View all screening results for this partner"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Screening Results'),
            'res_model': 'aml.screening.result',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
        }

    def action_view_goaml_reports(self):
        """View goAML reports for this partner"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('goAML Reports'),
            'res_model': 'aml.goaml.report',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
            'context': {'default_partner_id': self.id},
        }

    def action_view_alerts(self):
        """View transaction alerts for this partner"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Transaction Alerts'),
            'res_model': 'aml.transaction.alert',
            'view_mode': 'list,form',
            'domain': [('partner_id', '=', self.id)],
        }
