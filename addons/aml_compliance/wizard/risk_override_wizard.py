# -*- coding: utf-8 -*-
"""
Risk Override Wizard

Allows a compliance officer or MLRO to manually override the
computed risk level with a mandatory justification.
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class RiskOverrideWizard(models.TransientModel):
    _name = 'aml.risk.override.wizard'
    _description = 'Risk Level Override Wizard'

    assessment_id = fields.Many2one(
        'aml.risk.assessment',
        string='Assessment',
        required=True,
        readonly=True,
    )

    current_risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('very_high', 'Very High'),
    ], string='Current Risk Level', readonly=True)

    new_risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('very_high', 'Very High'),
    ], string='New Risk Level', required=True)

    reason = fields.Text(
        string='Justification',
        required=True,
        help='Provide detailed justification for overriding the computed risk level. '
             'This is required for audit trail purposes per CBUAE regulations.',
    )

    def action_confirm_override(self):
        """Apply the risk override"""
        self.ensure_one()
        if not self.reason or len(self.reason.strip()) < 20:
            raise UserError(
                _('Override justification must be at least 20 characters for audit compliance.')
            )

        assessment = self.assessment_id
        assessment.write({
            'final_risk_level': self.new_risk_level,
            'is_overridden': True,
            'override_reason': self.reason,
            'override_user_id': self.env.uid,
            'override_date': fields.Datetime.now(),
            'state': 'overridden',
        })

        assessment.message_post(
            body=_(
                'Risk level manually overridden from <b>%s</b> to <b>%s</b><br/>'
                '<b>Justification:</b> %s<br/>'
                '<b>Overridden by:</b> %s',
                dict(assessment._fields['computed_risk_level'].selection).get(
                    self.current_risk_level, self.current_risk_level),
                dict(assessment._fields['final_risk_level'].selection).get(
                    self.new_risk_level, self.new_risk_level),
                self.reason,
                self.env.user.name,
            ),
            message_type='notification',
        )

        _logger.info(
            'Risk assessment %s overridden from %s to %s by %s. Reason: %s',
            assessment.name,
            self.current_risk_level,
            self.new_risk_level,
            self.env.user.login,
            self.reason,
        )

        return {'type': 'ir.actions.act_window_close'}
