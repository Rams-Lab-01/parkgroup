# -*- coding: utf-8 -*-
"""
Extend kyc.application to trigger risk assessment on approval
and display risk information on the KYC form.
"""

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class KYCApplicationAML(models.Model):
    _inherit = 'kyc.application'

    risk_assessment_ids = fields.One2many(
        'aml.risk.assessment',
        'kyc_application_id',
        string='Risk Assessments',
    )

    risk_assessment_count = fields.Integer(
        string='# Risk Assessments',
        compute='_compute_risk_assessment_count',
    )

    current_risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('very_high', 'Very High'),
    ], string='Current Risk Level', compute='_compute_current_risk_level', store=True)

    def _compute_risk_assessment_count(self):
        for rec in self:
            rec.risk_assessment_count = len(rec.risk_assessment_ids)

    @api.depends('risk_assessment_ids.final_risk_level', 'risk_assessment_ids.state')
    def _compute_current_risk_level(self):
        for rec in self:
            approved = rec.risk_assessment_ids.filtered(
                lambda r: r.state in ('approved', 'reviewed', 'computed')
            ).sorted('assessment_date', reverse=True)
            rec.current_risk_level = approved[0].final_risk_level if approved else False

    def action_trigger_risk_assessment(self):
        """Manually trigger a risk assessment from KYC form"""
        self.ensure_one()
        assessment = self.env['aml.risk.assessment'].create({
            'partner_id': self.partner_id.id,
            'kyc_application_id': self.id,
            'assessment_type': 'initial' if not self.risk_assessment_ids else 'trigger',
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

    def action_view_risk_assessments(self):
        """View all risk assessments for this KYC application"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Risk Assessments'),
            'res_model': 'aml.risk.assessment',
            'view_mode': 'list,form',
            'domain': [('kyc_application_id', '=', self.id)],
            'context': {
                'default_kyc_application_id': self.id,
                'default_partner_id': self.partner_id.id,
            },
        }

    def action_approve(self):
        """Continue AML workflow automatically once KYC is approved.

        Flow:
        1) Create and compute risk assessment if one does not already exist.
        2) Run sanctions screening for the approved partner.
        3) Create activities for AML review if screening potential matches exist.
        """
        res = super().action_approve()

        for rec in self.filtered(lambda r: r.state == 'approved' and r.partner_id):
            existing_assessment = self.env['aml.risk.assessment'].search([
                ('kyc_application_id', '=', rec.id),
                ('state', 'in', ('computed', 'reviewed', 'approved', 'overridden')),
            ], order='assessment_date desc', limit=1)

            if not existing_assessment:
                assessment = self.env['aml.risk.assessment'].create({
                    'partner_id': rec.partner_id.id,
                    'kyc_application_id': rec.id,
                    'assessment_type': 'initial',
                })
                assessment.action_compute_risk()
                rec.message_post(
                    body=_('AML risk assessment %s has been auto-created from KYC approval.', assessment.name),
                    message_type='notification',
                )

            screening_results = self.env['aml.screening.result'].screen_partner(
                rec.partner_id,
                screening_type='onboarding',
            )

            if screening_results:
                aml_group = self.env.ref('aml_compliance.group_aml_officer', raise_if_not_found=False)
                aml_user = aml_group.users[:1] if aml_group else self.env.user
                rec.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=aml_user.id,
                    summary=_('AML Screening Review Required — %s', rec.kyc_id),
                    note=_('Potential sanctions match(es) detected for %s. Review screening results before completing onboarding.', rec.partner_id.display_name),
                )
                rec.message_post(
                    body=_('Sanctions screening produced %s potential match(es). AML review activity created.', len(screening_results)),
                    message_type='notification',
                    subtype_xmlid='mail.mt_note',
                )

        return res
