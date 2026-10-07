"""SGC Leaderboard — a single page that ranks the sales team across the
metrics that actually matter for the gamification design: karma, MTD revenue,
MTD deals closed, weekly meetings, monthly revivals, and total badges.

The quarterly top-3 podium applies the closed-deal eligibility gate from
the design (only reps who have won at least one deal this quarter can claim
a prize). Reps without a win still appear on the monthly leaderboard.
"""

from dateutil.relativedelta import relativedelta

from odoo import fields, http
from odoo.http import request


class SGCLeaderboardController(http.Controller):

    @http.route('/sgc/leaderboard', type='http', auth='user', website=True, csrf=False)
    def leaderboard(self, **kwargs):
        env = request.env
        today = fields.Date.context_today(env.user)
        month_start = today.replace(day=1)
        month_end = month_start + relativedelta(months=1)
        # Quarter start: first day of the calendar quarter containing today.
        quarter_start = today.replace(day=1) - relativedelta(months=(today.month - 1) % 3)
        quarter_end = quarter_start + relativedelta(months=3)
        # Week start (Monday-aligned)
        week_start = today - relativedelta(days=today.weekday())

        # The ladder ranks sales team members only: a linked hr.employee, on
        # a crm.team. Admin & system accounts — users holding the
        # Administrator (Access Rights) or Settings groups — are excluded
        # from the competition even if they sit on a sales team.
        admin_group_ids = [
            env.ref('base.group_erp_manager').id,
            env.ref('base.group_system').id,
        ]
        sales_team_user_ids = env['crm.team.member'].sudo().search([]).mapped('user_id').ids
        users = env['res.users'].sudo().search_read(
            [('share', '=', False),
             ('active', '=', True),
             ('employee_ids', '!=', False),
             ('id', 'in', sales_team_user_ids),
             ('group_ids', 'not in', admin_group_ids)],
            ['id', 'name', 'display_name', 'image_128', 'karma'],
        )
        user_ids = [u['id'] for u in users]
        user_by_id = {u['id']: u for u in users}

        # MTD revenue + deals closed (must be a won stage)
        env.cr.execute("""
            SELECT user_id,
                   COALESCE(SUM(expected_revenue), 0) AS revenue,
                   COUNT(*) AS deals
              FROM crm_lead
              JOIN crm_stage ON crm_stage.id = crm_lead.stage_id
             WHERE crm_stage.is_won = TRUE
               AND crm_lead.date_closed >= %s
               AND crm_lead.date_closed < %s
               AND crm_lead.user_id = ANY(%s)
          GROUP BY user_id
        """, (month_start, today + relativedelta(days=1), user_ids))
        for row in env.cr.dictfetchall():
            user_by_id[row['user_id']]['revenue_mtd'] = float(row['revenue'] or 0)
            user_by_id[row['user_id']]['deals_mtd'] = int(row['deals'] or 0)

        # Quarterly revenue + deals (for the prize pool podium)
        env.cr.execute("""
            SELECT user_id,
                   COALESCE(SUM(expected_revenue), 0) AS revenue,
                   COUNT(*) AS deals
              FROM crm_lead
              JOIN crm_stage ON crm_stage.id = crm_lead.stage_id
             WHERE crm_stage.is_won = TRUE
               AND crm_lead.date_closed >= %s
               AND crm_lead.date_closed < %s
               AND crm_lead.user_id = ANY(%s)
          GROUP BY user_id
        """, (quarter_start, today + relativedelta(days=1), user_ids))
        for row in env.cr.dictfetchall():
            user_by_id[row['user_id']]['revenue_qtd'] = float(row['revenue'] or 0)
            user_by_id[row['user_id']]['deals_qtd'] = int(row['deals'] or 0)

        # Weekly meetings (calendar.event created by the user, on an opportunity)
        env.cr.execute("""
            SELECT create_uid, COUNT(*) AS meetings
              FROM calendar_event
             WHERE opportunity_id IS NOT NULL
               AND start >= %s
               AND start < %s
               AND create_uid = ANY(%s)
          GROUP BY create_uid
        """, (week_start, today + relativedelta(days=1), user_ids))
        for row in env.cr.dictfetchall():
            user_by_id[row['create_uid']]['meetings_w'] = int(row['meetings'] or 0)

        # Monthly revivals (confirmed)
        env.cr.execute("""
            SELECT x_revived_by_id, COUNT(*) AS revivals
              FROM crm_lead
             WHERE x_revival_confirmed = TRUE
               AND x_revived_date >= %s
               AND x_revived_date < %s
               AND x_revived_by_id = ANY(%s)
          GROUP BY x_revived_by_id
        """, (month_start, today + relativedelta(days=1), user_ids))
        for row in env.cr.dictfetchall():
            user_by_id[row['x_revived_by_id']]['revivals_mtd'] = int(row['revivals'] or 0)

        # Total badges (all-time)
        env.cr.execute("""
            SELECT user_id, COUNT(*) AS badges
              FROM gamification_badge_user
             WHERE user_id = ANY(%s)
          GROUP BY user_id
        """, (user_ids,))
        for row in env.cr.dictfetchall():
            user_by_id[row['user_id']]['badges_total'] = int(row['badges'] or 0)

        # Default zeros for any user missing from a query
        for u in users:
            u.setdefault('revenue_mtd', 0.0)
            u.setdefault('deals_mtd', 0)
            u.setdefault('revenue_qtd', 0.0)
            u.setdefault('deals_qtd', 0)
            u.setdefault('meetings_w', 0)
            u.setdefault('revivals_mtd', 0)
            u.setdefault('badges_total', 0)

        # Quarterly podium — only reps with at least one closed deal this quarter
        podium_eligible = sorted(
            [u for u in users if u.get('deals_qtd', 0) >= 1],
            key=lambda u: u['revenue_qtd'],
            reverse=True,
        )[:3]
        prizes = [1000, 600, 400]
        podium = []
        for i, u in enumerate(podium_eligible):
            podium.append({
                'rank': i + 1,
                'user': u,
                'prize_aed': prizes[i] if i < len(prizes) else 0,
                'revenue_qtd': u['revenue_qtd'],
                'deals_qtd': u['deals_qtd'],
            })

        # Monthly leaderboard — ranked by karma (the headline metric), with
        # revenue / deals / meetings / revivals / badges as supporting columns.
        rows = sorted(users, key=lambda u: u.get('karma', 0), reverse=True)
        for i, u in enumerate(rows):
            u['rank'] = i + 1

        total_prize_pool = sum(p['prize_aed'] for p in podium)

        currency = request.env.company.currency_id

        return request.render('sgc_employee_badges.sgc_leaderboard_template', {
            'podium': podium,
            'rows': rows,
            'today': today,
            'month_start': month_start,
            'month_end': month_end,
            'quarter_start': quarter_start,
            'quarter_end': quarter_end,
            'week_start': week_start,
            'total_prize_pool': total_prize_pool,
            'currency': currency,
            'current_user_id': request.env.uid,
        })

    @http.route('/sgc/leaderboard/mini', type='http', auth='user', website=True, csrf=False)
    def leaderboard_mini(self, **kwargs):
        env = request.env
        today = fields.Date.context_today(env.user)
        month_start = today.replace(day=1)
        # Sales team members only (linked employee, on a crm.team); admin &
        # system accounts do not compete even if they sit on a sales team.
        admin_group_ids = [
            env.ref('base.group_erp_manager').id,
            env.ref('base.group_system').id,
        ]
        sales_team_user_ids = env['crm.team.member'].sudo().search([]).mapped('user_id').ids
        users = env['res.users'].sudo().search_read(
            [('share', '=', False),
             ('active', '=', True),
             ('employee_ids', '!=', False),
             ('id', 'in', sales_team_user_ids),
             ('group_ids', 'not in', admin_group_ids)],
            ['id', 'name', 'display_name', 'karma'])
        # Sort by karma descending and take top 5
        users_sorted = sorted(users, key=lambda u: u.get('karma', 0), reverse=True)[:5]
        currency = env.company.currency_id
        return request.render('sgc_employee_badges.sgc_leaderboard_mini', {
            'users': users_sorted,
            'currency': currency,
            'today': today,
        })
