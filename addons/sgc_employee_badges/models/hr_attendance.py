from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class HrAttendance(models.Model):
    _inherit = 'hr.attendance'

    x_excused_late = fields.Boolean(
        string='Excused Late',
        default=False,
        help='Documented transport/medical reason for a late check-in. '
             'Excluded from the Policy Enforcer punctuality calculation '
             'on both sides -- neither counted as on-time nor held against it.',
    )

    @api.model
    def _cron_award_steady_anchor(self):
        """Quarterly: attendance rate over the trailing 3 months against
        each employee's own working calendar. Expected working days are
        approximated from the calendar's weekly attendance pattern (day-of
        week only) -- it doesn't account for approved leave or company
        holidays, which would need hr_holidays cross-referencing to do
        precisely. Simplification is noted, not hidden."""
        badge = self.env.ref('sgc_employee_badges.badge_steady_anchor', raise_if_not_found=False)
        if not badge:
            return
        today = fields.Date.context_today(self)
        quarter_start = today - relativedelta(months=3)
        BadgeUser = self.env['gamification.badge.user'].sudo()

        employees = self.env['hr.employee'].search([('user_id', '!=', False)])
        for employee in employees:
            cal = employee.resource_calendar_id
            if not cal:
                continue
            working_days = {int(a.dayofweek) for a in cal.attendance_ids}
            if not working_days:
                continue
            expected = 0
            d = quarter_start
            while d <= today:
                if d.weekday() in working_days:
                    expected += 1
                d += timedelta(days=1)
            if expected == 0:
                continue

            attendances = self.search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', quarter_start),
                ('check_in', '<=', today),
            ])
            attended_days = {a.check_in.date() for a in attendances}
            rate = len(attended_days) / expected * 100
            if rate < 95:
                continue

            already = BadgeUser.search_count([
                ('badge_id', '=', badge.id),
                ('user_id', '=', employee.user_id.id),
                ('create_date', '>=', quarter_start),
            ])
            if already:
                continue
            BadgeUser.create({'badge_id': badge.id, 'user_id': employee.user_id.id})
