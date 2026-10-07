import json
from datetime import datetime, timedelta
from collections import OrderedDict

from odoo import http
from odoo.http import request, Response


class BigScreenDashboard(http.Controller):

    @http.route('/dashboard/big-screen', type='http', auth='public', website=True, csrf=False)
    def big_screen(self, **kwargs):
        return request.render('sgc_crm_dashboard.big_screen_template')

    @http.route('/dashboard/big-screen/data', type='http', auth='public', csrf=False)
    def big_screen_data(self, **kwargs):
        cr = request.env.cr
        now = datetime.now()

        # Resolve semantic stages by name against this tenant's real pipeline
        # (shared resolver with the backend dashboard) instead of hardcoded ids.
        sm = request.env["crm.dashboard"].sudo()._stage_map()
        won_stage_ids = sm["won"] or []
        won_stage_sql = ",".join(map(str, won_stage_ids)) if won_stage_ids else "0"
        rd = sm["research_done"] or -1
        oe = sm["outreach_email"] or -1
        mb = sm["meeting_booked"] or -1
        fu = sm["follow_up"] or -1

        def _stage_cnt(stage_id):
            if not stage_id:
                return 0
            cr.execute("SELECT count(*) FROM crm_lead WHERE active = true AND stage_id = %s", (stage_id,))
            return cr.fetchone()[0] or 0

        # ─── KPIs ───────────────────────────────────────────────
        cr.execute("SELECT count(*) FROM crm_lead")
        total_leads = cr.fetchone()[0]

        follow_up = _stage_cnt(sm["follow_up"])

        # Meeting Booked (-> Proposition on simpler pipelines)
        booked = _stage_cnt(sm["meeting_booked"])

        # Won: stage_id is won stage
        cr.execute(f"""
            SELECT count(*) FROM crm_lead
            WHERE active = true AND stage_id IN ({won_stage_sql})
        """)
        won = cr.fetchone()[0]

        # Research Done (-> Qualified on simpler pipelines)
        research_done = _stage_cnt(sm["research_done"])

        # Outreach Email (-> absent on simpler pipelines => 0)
        outreach_email = _stage_cnt(sm["outreach_email"])

        # Objection Ranking: count of objections
        cr.execute("""
            SELECT o.name->>'en_US' as objection, COUNT(l.id) as count
            FROM crm_lead l
            JOIN crm_lead_objection_rel rel ON rel.lead_id = l.id
            JOIN crm_objection o ON o.id = rel.objection_id
            WHERE l.active = true
            GROUP BY o.name
            ORDER BY count DESC
        """)
        objection_ranking = [{"objection": r[0], "count": r[1]} for r in cr.fetchall()]

        cr.execute("""
            SELECT COALESCE(SUM(amount_total), 0) FROM sale_order
            WHERE state IN ('sale', 'done')
        """)
        est_revenue = float(cr.fetchone()[0])

        # ─── Sales Rankings ─────────────────────────────────────
        # Lead Activity: most leads assigned (active users only)
        cr.execute("""
            SELECT u.id, COALESCE(p.name, u.login) as name, count(l.id) as cnt
            FROM crm_lead l
            JOIN res_users u ON l.user_id = u.id
            LEFT JOIN res_partner p ON u.partner_id = p.id
            WHERE u.active = true AND u.id > 2
            GROUP BY u.id, p.name, u.login
            ORDER BY cnt DESC LIMIT 10
        """)
        rank_leads = [{"id": r[0], "name": r[1], "count": r[2]} for r in cr.fetchall()]

        # Meeting Booked ranking
        cr.execute(f"""
            SELECT u.id, COALESCE(p.name, u.login) as name, count(l.id) as cnt
            FROM crm_lead l
            JOIN res_users u ON l.user_id = u.id
            LEFT JOIN res_partner p ON u.partner_id = p.id
            WHERE u.active = true AND u.id > 2 AND l.active = true AND l.stage_id = {mb}
            GROUP BY u.id, p.name, u.login
            ORDER BY cnt DESC LIMIT 10
        """)
        rank_booking = [{"id": r[0], "name": r[1], "count": r[2]} for r in cr.fetchall()]

        # Won ranking: stage_id is won stage
        cr.execute(f"""
            SELECT u.id, COALESCE(p.name, u.login) as name, count(l.id) as cnt
            FROM crm_lead l
            JOIN res_users u ON l.user_id = u.id
            LEFT JOIN res_partner p ON u.partner_id = p.id
            WHERE u.active = true AND u.id > 2 AND l.active = true AND l.stage_id IN ({won_stage_sql})
            GROUP BY u.id, p.name, u.login
            ORDER BY cnt DESC LIMIT 10
        """)
        rank_won = [{"id": r[0], "name": r[1], "count": r[2]} for r in cr.fetchall()]

        # Activity: most recent activities (last 30 days)
        cr.execute("""
            SELECT u.id, COALESCE(p.name, u.login) as name, count(a.id) as cnt
            FROM mail_activity a
            JOIN res_users u ON a.user_id = u.id
            LEFT JOIN res_partner p ON u.partner_id = p.id
            WHERE u.active = true AND a.user_id > 2
                AND a.create_date >= NOW() - INTERVAL '30 days'
            GROUP BY u.id, p.name, u.login
            ORDER BY cnt DESC LIMIT 10
        """)
        rank_activity = [{"id": r[0], "name": r[1], "count": r[2]} for r in cr.fetchall()]

        # Research Done ranking (-> Qualified)
        cr.execute(f"""
            SELECT u.id, COALESCE(p.name, u.login) as name, count(l.id) as cnt
            FROM crm_lead l
            JOIN res_users u ON l.user_id = u.id
            LEFT JOIN res_partner p ON u.partner_id = p.id
            WHERE u.active = true AND u.id > 2 AND l.active = true AND l.stage_id = {rd}
            GROUP BY u.id, p.name, u.login
            ORDER BY cnt DESC LIMIT 10
        """)
        rank_research = [{"id": r[0], "name": r[1], "count": r[2]} for r in cr.fetchall()]

        # Outreach Email ranking (-> absent => empty)
        cr.execute(f"""
            SELECT u.id, COALESCE(p.name, u.login) as name, count(l.id) as cnt
            FROM crm_lead l
            JOIN res_users u ON l.user_id = u.id
            LEFT JOIN res_partner p ON u.partner_id = p.id
            WHERE u.active = true AND u.id > 2 AND l.active = true AND l.stage_id = {oe}
            GROUP BY u.id, p.name, u.login
            ORDER BY cnt DESC LIMIT 10
        """)
        rank_outreach = [{"id": r[0], "name": r[1], "count": r[2]} for r in cr.fetchall()]

        # ─── Sales Team Bar Chart ───────────────────────────────
        cr.execute(f"""
            SELECT t.name, count(l.id) as leads,
                SUM(CASE WHEN l.active=true AND l.stage_id IN ({won_stage_sql}) THEN 1 ELSE 0 END) as won
            FROM crm_team t
            LEFT JOIN crm_lead l ON l.team_id = t.id
            WHERE t.active = true
            GROUP BY t.name
            ORDER BY leads DESC
        """)
        teams = [{"name": r[0], "leads": r[1], "won": r[2]} for r in cr.fetchall()]

        # ─── Daily Activity Line Chart (last 30 days per top salesperson) ──
        # Get top 6 salespeople by activity count (active users only)
        cr.execute("""
            SELECT u.id, COALESCE(p.name, u.login) as name
            FROM mail_activity a
            JOIN res_users u ON a.user_id = u.id
            LEFT JOIN res_partner p ON u.partner_id = p.id
            WHERE u.active = true AND a.user_id > 2
                AND a.create_date >= NOW() - INTERVAL '30 days'
            GROUP BY u.id, p.name, u.login
            ORDER BY count(a.id) DESC LIMIT 6
        """)
        top_users = cr.fetchall()

        daily_data = []
        days = 30
        for i in range(days, -1, -1):
            d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
            daily_data.append({"date": d, "users": {}})

        for uid, uname in top_users:
            cr.execute("""
                SELECT DATE(a.create_date) as day, count(*) as cnt
                FROM mail_activity a
                WHERE a.user_id = %s
                    AND a.create_date >= NOW() - INTERVAL '%s days'
                GROUP BY day ORDER BY day
            """, (uid, days))
            for row in cr.fetchall():
                day_str = row[0].strftime("%Y-%m-%d") if hasattr(row[0], 'strftime') else str(row[0])
                for entry in daily_data:
                    if entry["date"] == day_str:
                        entry["users"][uname] = row[1]

        daily_chart = {
            "labels": [e["date"][-5:] for e in daily_data],  # MM-DD
            "datasets": []
        }
        colors = ["#7D7EAF", "#1EC198", "#FFCA71", "#E74C3C", "#BD85BA", "#0dcaf0"]
        for idx, (uid, uname) in enumerate(top_users):
            daily_chart["datasets"].append({
                "label": uname,
                "data": [e["users"].get(uname, 0) for e in daily_data],
                "borderColor": colors[idx % len(colors)],
                "backgroundColor": colors[idx % len(colors)] + "20",
                "tension": 0.3,
                "fill": False,
                "pointRadius": 2,
            })

        # ─── Sales Funnel (progression stages only) ────────────
        cr.execute("""
            SELECT s.id, s.name->>'en_US' as stage_name, s.sequence, s.is_won,
                   COUNT(l.id) as lead_count
            FROM crm_stage s
            LEFT JOIN crm_lead l ON l.stage_id = s.id AND l.active = true
            GROUP BY s.id, s.name, s.sequence, s.is_won
            ORDER BY s.sequence
        """)
        funnel = []
        # Show ALL stages (including dead ones) for full funnel visualization
        for r in cr.fetchall():
            name = r[1]
            funnel.append({
                "id": r[0],
                "name": name,
                "sequence": r[2],
                "is_won": r[3],
                "count": r[4],
            })

        result = {
            "kpi": {
                "total_leads": total_leads,
                "follow_up": follow_up,
                "booked": booked,
                "research_done": research_done,
                "outreach_email": outreach_email,
                "won": won,
                "est_revenue": est_revenue,
            },
            "objection_ranking": objection_ranking,
            "rank_leads": rank_leads,
            "rank_booking": rank_booking,
            "rank_won": rank_won,
            "rank_activity": rank_activity,
            "rank_research": rank_research,
            "rank_outreach": rank_outreach,
            "teams": teams,
            "daily_chart": daily_chart,
            "funnel": funnel,
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        }
        return Response(
            json.dumps(result),
            content_type='application/json',
            status=200,
        )
