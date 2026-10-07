from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

# A revival only "confirms" -- and counts toward Growth Driver / the
# leaderboard -- if real follow-up work happens within this many days.
# A lead that gets reactivated and then untouched doesn't count.
REVIVAL_CONFIRMATION_WINDOW_DAYS = 14


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    x_revived_by_id = fields.Many2one(
        'res.users', string='Revived By', readonly=True, copy=False,
        help='Set automatically when this lead is reactivated after having been lost.',
    )
    x_revived_date = fields.Datetime(string='Revived On', readonly=True, copy=False)
    x_revival_confirmed = fields.Boolean(
        string='Revival Confirmed', default=False, readonly=True, copy=False,
        help='True once a real follow-up (a meeting booked, or the lead won) '
             'happens within %d days of the revival.' % REVIVAL_CONFIRMATION_WINDOW_DAYS,
    )

    def write(self, vals):
        revived = self.env['crm.lead']
        if vals.get('active'):
            revived = self.filtered(lambda l: not l.active and l.lost_reason_id)
        result = super().write(vals)
        if revived:
            revived.write({
                'x_revived_by_id': self.env.uid,
                'x_revived_date': fields.Datetime.now(),
                'x_revival_confirmed': False,
            })
        return result

    def _cron_confirm_revivals(self):
        """Daily sweep: mark revivals as confirmed once a qualifying
        follow-up (meeting booked or lead won) has happened within the
        confirmation window. Leads past the window without a follow-up
        are left unconfirmed permanently (their revival didn't stick)."""
        Event = self.env['calendar.event']
        pending = self.search([
            ('x_revived_date', '!=', False),
            ('x_revival_confirmed', '=', False),
        ])
        for lead in pending:
            window_end = lead.x_revived_date + timedelta(days=REVIVAL_CONFIRMATION_WINDOW_DAYS)
            has_meeting = bool(Event.search_count([
                ('opportunity_id', '=', lead.id),
                ('create_uid', '=', lead.x_revived_by_id.id),
                ('start', '>=', lead.x_revived_date),
                ('start', '<=', window_end),
            ]))
            has_win = bool(
                lead.stage_id.is_won
                and lead.date_closed
                and lead.x_revived_date <= lead.date_closed <= window_end
            )
            if has_meeting or has_win:
                lead.x_revival_confirmed = True

    @api.model
    def _cron_award_growth_driver(self):
        """Quarterly: whoever confirmed at least one revival in the
        trailing 3 months gets Growth Driver. Badge cadence is quarterly
        per design; the leaderboard's own revivals-count column (separate
        from this badge) is what moves monthly."""
        badge = self.env.ref('sgc_employee_badges.badge_growth_driver', raise_if_not_found=False)
        if not badge:
            return
        today = fields.Date.context_today(self)
        quarter_start = today - relativedelta(months=3)
        self.env.cr.execute("""
            SELECT x_revived_by_id, COUNT(*) AS cnt
              FROM crm_lead
             WHERE x_revival_confirmed = TRUE
               AND x_revived_date >= %s
               AND x_revived_by_id IS NOT NULL
          GROUP BY x_revived_by_id
        """, (quarter_start,))
        BadgeUser = self.env['gamification.badge.user'].sudo()
        for row in self.env.cr.dictfetchall():
            if row['cnt'] < 1:
                continue
            already = BadgeUser.search_count([
                ('badge_id', '=', badge.id),
                ('user_id', '=', row['x_revived_by_id']),
                ('create_date', '>=', quarter_start),
            ])
            if already:
                continue
            BadgeUser.create({'badge_id': badge.id, 'user_id': row['x_revived_by_id']})
