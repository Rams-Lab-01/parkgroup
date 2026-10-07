from dateutil.relativedelta import relativedelta

from odoo import api, fields, models


class GamificationBadge(models.Model):
    _inherit = 'gamification.badge'

    point_value = fields.Integer(
        string='Point Value',
        default=0,
        help='Karma points awarded to a user each time this badge is granted.',
    )

    @api.model
    def _cron_award_top_earner(self):
        """Monthly: whoever has the highest won-deal revenue this month
        gets Top Earner. A relative ranking (not a threshold) can't be
        expressed as a standard goal_definition, so this runs as its own
        cron. Metric is expected_revenue on crm.lead reaching a won stage
        -- the plainest reading of "earner" until told otherwise."""
        badge = self.env.ref('sgc_employee_badges.badge_top_earner', raise_if_not_found=False)
        if not badge:
            return
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        month_end = month_start + relativedelta(months=1)
        self.env.cr.execute("""
            SELECT user_id, SUM(expected_revenue) AS total
              FROM crm_lead
              JOIN crm_stage ON crm_stage.id = crm_lead.stage_id
             WHERE crm_stage.is_won = TRUE
               AND crm_lead.date_closed >= %s
               AND crm_lead.date_closed < %s
               AND crm_lead.user_id IS NOT NULL
          GROUP BY user_id
          ORDER BY total DESC
             LIMIT 1
        """, (month_start, month_end))
        row = self.env.cr.dictfetchone()
        if not row or not row['total']:
            return
        already = self.env['gamification.badge.user'].sudo().search_count([
            ('badge_id', '=', badge.id),
            ('user_id', '=', row['user_id']),
            ('create_date', '>=', month_start),
        ])
        if already:
            return
        self.env['gamification.badge.user'].sudo().create({
            'badge_id': badge.id,
            'user_id': row['user_id'],
        })

    # Revenue Generator's repeatable tier ladder -- 1,000 AED is the first
    # real milestone, then every 50,000 AED climbs a tier, capping at
    # Legendary weight (200) beyond 200,000 so it stays open-ended.
    @api.model
    def _revenue_tier(self, total):
        if total < 1000:
            return 0
        if total < 50000:
            return 1
        if total < 100000:
            return 2
        if total < 150000:
            return 3
        if total < 200000:
            return 4
        return 4 + int((total - 200000) // 50000) + 1

    @api.model
    def _revenue_tier_points(self, tier):
        return {1: 25, 2: 50, 3: 100}.get(tier, 200)

    @api.model
    def _cron_award_revenue_generator(self):
        """Monthly: check each rep's cumulative won-deal revenue and grant
        any newly-crossed tiers. Idempotent -- grants only the tiers beyond
        however many this user already holds."""
        badge = self.env.ref('sgc_employee_badges.badge_revenue_generator', raise_if_not_found=False)
        if not badge:
            return
        self.env.cr.execute("""
            SELECT user_id, SUM(expected_revenue) AS total
              FROM crm_lead
              JOIN crm_stage ON crm_stage.id = crm_lead.stage_id
             WHERE crm_stage.is_won = TRUE
               AND crm_lead.user_id IS NOT NULL
          GROUP BY user_id
        """)
        BadgeUser = self.env['gamification.badge.user'].sudo()
        for row in self.env.cr.dictfetchall():
            user_id, total = row['user_id'], row['total'] or 0
            target_tier = self._revenue_tier(total)
            if target_tier <= 0:
                continue
            already = BadgeUser.search_count([('badge_id', '=', badge.id), ('user_id', '=', user_id)])
            for tier in range(already + 1, target_tier + 1):
                points = self._revenue_tier_points(tier)
                BadgeUser.with_context(karma_points_override=points).create({
                    'badge_id': badge.id,
                    'user_id': user_id,
                })
