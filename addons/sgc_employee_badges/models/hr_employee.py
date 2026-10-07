from datetime import timedelta

from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    x_gamification_start_date = fields.Date(
        string='Gamification Start Date',
        compute='_compute_gamification_start_date',
        store=True,
        help='Next Monday on/after date_start. New joiners are excluded from '
             'weekly/monthly gamification challenges until this date so a '
             'partial first week is never counted against them.',
    )

    @api.depends('date_start')
    def _compute_gamification_start_date(self):
        for employee in self:
            if not employee.date_start:
                employee.x_gamification_start_date = False
                continue
            start = employee.date_start
            days_ahead = (7 - start.weekday()) % 7
            employee.x_gamification_start_date = start + timedelta(days=days_ahead)
