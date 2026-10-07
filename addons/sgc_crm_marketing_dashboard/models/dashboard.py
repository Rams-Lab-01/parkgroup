# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from datetime import date, datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Contract states that count as realised revenue (base + EOI workflow vocab).
SIGNED_STATES = ("signed", "spa_signed", "completed")


class SgcCrmMarketingDashboard(models.AbstractModel):
    """Server side of the CRM & Marketing dashboard.

    Answers, live from real records: what is happening with potential buyers,
    how each campaign is performing, and what the marketing return actually is.
    """
    _name = "sgc.crm.marketing.dashboard"
    _description = "SGC CRM & Marketing Dashboard"

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def _won_stage_ids(self):
        return self.env["crm.stage"].search([("is_won", "=", True)]).ids

    @api.model
    def _period_start(self, period):
        today = fields.Date.context_today(self)
        if period == "month":
            return today.replace(day=1)
        if period == "quarter":
            return date(today.year, ((today.month - 1) // 3) * 3 + 1, 1)
        if period == "year":
            return date(today.year, 1, 1)
        return None  # 'all'

    @api.model
    def _group(self, model, domain, groupby, aggregates):
        return self.env[model].sudo()._read_group(domain, groupby, aggregates)

    # ─────────────────────────────────────────────────────────────────────
    # Data feed
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def get_dashboard_data(self, period="month"):
        cr = self.env.cr
        Lead = self.env["crm.lead"].sudo()
        won_ids = self._won_stage_ids()
        period_start = self._period_start(period)

        # ── Potential buyers: the live pipeline ──────────────────────────
        open_domain = [("active", "=", True)]
        open_count = Lead.search_count(open_domain)

        cr.execute("""
            SELECT COALESCE(SUM(expected_revenue), 0),
                   COALESCE(SUM(expected_revenue * probability / 100.0), 0)
              FROM crm_lead
             WHERE active = true
        """)
        pipeline_value, weighted_value = (float(x or 0.0) for x in cr.fetchone())

        won = Lead.search_count([("stage_id", "in", won_ids)]) if won_ids else 0
        lost = Lead.search_count(["|", ("active", "=", False), ("probability", "=", 0)])
        closed = won + lost
        win_rate = round(won / closed * 100.0, 1) if closed else 0.0
        avg_deal = round(pipeline_value / open_count, 0) if open_count else 0.0

        # ── New business in the period ───────────────────────────────────
        new_domain = []
        if period_start:
            new_domain = [("create_date", ">=", fields.Datetime.to_string(
                datetime.combine(period_start, datetime.min.time())))]
        new_leads = Lead.search_count(new_domain)
        new_won = Lead.search_count(
            new_domain + [("stage_id", "in", won_ids)]) if won_ids else 0

        # ── Pipeline by stage / source / owner ───────────────────────────
        by_stage = []
        for stage, value, count in self._group(
                "crm.lead", open_domain, ["stage_id"],
                ["expected_revenue:sum", "id:count"]):
            if count:
                by_stage.append({
                    "id": stage.id if stage else False,
                    "name": stage.name if stage else _("Unassigned"),
                    "count": count, "value": round(value or 0.0),
                })
        by_stage.sort(key=lambda r: r["count"], reverse=True)

        by_source = []
        for source, count in self._group(
                "crm.lead", open_domain, ["source_id"], ["id:count"]):
            by_source.append({
                "id": source.id if source else False,
                "name": source.name if source else _("Unassigned"),
                "count": count,
            })
        by_source.sort(key=lambda r: r["count"], reverse=True)

        by_owner = []
        for user, count in self._group(
                "crm.lead", open_domain, ["user_id"], ["id:count"]):
            by_owner.append({
                "id": user.id if user else False,
                "name": user.name if user else _("Unassigned"),
                "count": count,
            })
        by_owner.sort(key=lambda r: r["count"], reverse=True)

        # ── Aging of the open pipeline (SLA view) ────────────────────────
        cr.execute("""
            SELECT
              COALESCE(SUM(CASE WHEN (CURRENT_DATE - date_last_stage_update::date) BETWEEN 0 AND 7  THEN 1 ELSE 0 END),0) AS b0,
              COALESCE(SUM(CASE WHEN (CURRENT_DATE - date_last_stage_update::date) BETWEEN 8 AND 30 THEN 1 ELSE 0 END),0) AS b1,
              COALESCE(SUM(CASE WHEN (CURRENT_DATE - date_last_stage_update::date) BETWEEN 31 AND 60 THEN 1 ELSE 0 END),0) AS b2,
              COALESCE(SUM(CASE WHEN (CURRENT_DATE - date_last_stage_update::date) > 60 THEN 1 ELSE 0 END),0) AS b3
              FROM crm_lead
             WHERE active = true AND date_last_stage_update IS NOT NULL
        """)
        aging = [{"bucket": b, "count": int(c or 0)} for b, c in zip(
            ("0-7d", "8-30d", "31-60d", "60d+"), cr.fetchone())]

        # ── Trend: last 6 months created / won / lost ────────────────────
        cr.execute("""
            SELECT TO_CHAR(m, 'YYYY-MM') AS month,
                   COALESCE(SUM(created),0), COALESCE(SUM(won),0), COALESCE(SUM(lost),0)
              FROM (
                SELECT date_trunc('month', create_date) AS m,
                       1 AS created, 0 AS won, 0 AS lost FROM crm_lead
                UNION ALL
                SELECT date_trunc('month', date_closed) AS m,
                       0, CASE WHEN stage_id = ANY(%s) THEN 1 ELSE 0 END,
                       CASE WHEN active = false THEN 1 ELSE 0 END
                  FROM crm_lead WHERE date_closed IS NOT NULL
              ) t
             GROUP BY month ORDER BY month
        """, (won_ids or [-1],))
        trend = [{"month": m, "created": int(c), "won": int(w), "lost": int(l)}
                 for m, c, w, l in cr.fetchall()][-6:]

        # ── Biggest live potential buyers ────────────────────────────────
        buyers = Lead.search_read(
            open_domain,
            ["name", "partner_id", "property_id", "stage_id", "expected_revenue",
             "probability", "user_id", "create_date", "source_id", "campaign_id"],
            order="expected_revenue desc, create_date desc", limit=15)
        buyers = [{
            "id": b["id"],
            "name": b["name"] or _("Unnamed"),
            "partner": b["partner_id"][1] if b["partner_id"] else "",
            "property": b["property_id"][1] if b["property_id"] else "",
            "stage": b["stage_id"][1] if b["stage_id"] else _("Unassigned"),
            "expected_revenue": b["expected_revenue"] or 0.0,
            "probability": b["probability"] or 0.0,
            "owner": b["user_id"][1] if b["user_id"] else "",
            "source": b["source_id"][1] if b["source_id"] else "",
            "campaign": b["campaign_id"][1] if b["campaign_id"] else "",
            "created": (b["create_date"].strftime("%Y-%m-%d") if b["create_date"] else ""),
        } for b in buyers]

        # ── Campaigns + marketing ROI ────────────────────────────────────
        # Campaign lead/opportunity/won counts.
        cr.execute("""
            SELECT c.id, c.name, COALESCE(c.marketing_cost, 0),
                   COUNT(l.id) AS leads,
                   COUNT(l.id) FILTER (WHERE l.active AND l.probability > 0
                                         AND l.probability < 100) AS opps,
                   COUNT(l.id) FILTER (WHERE l.stage_id = ANY(%s)) AS won
              FROM utm_campaign c
              LEFT JOIN crm_lead l ON l.campaign_id = c.id
             GROUP BY c.id, c.name, c.marketing_cost
             ORDER BY leads DESC
        """, (won_ids or [-1],))
        camp_rows = cr.fetchall()

        # Revenue attributed to each campaign through its winning leads'
        # sale contracts (the property-sale instrument).
        rev_sql = """
            SELECT l.campaign_id, COALESCE(SUM(sc.sale_price), 0), COUNT(DISTINCT sc.id)
              FROM sale_contract sc
              JOIN crm_lead l ON l.id = sc.lead_id
             WHERE l.campaign_id IS NOT NULL AND sc.state IN %s
        """
        rev_params = [SIGNED_STATES]
        if period_start:
            rev_sql += " AND sc.create_date >= %s"
            rev_params.append(datetime.combine(period_start, datetime.min.time()))
        rev_sql += " GROUP BY l.campaign_id"
        cr.execute(rev_sql, tuple(rev_params))
        revenue_by_campaign = {r[0]: (float(r[1] or 0.0), int(r[2] or 0))
                               for r in cr.fetchall()}

        campaigns = []
        for cid, cname, cost, leads, opps, won_c in camp_rows:
            revenue, won_deals = revenue_by_campaign.get(cid, (0.0, 0))
            cost = float(cost or 0.0)
            campaigns.append({
                "id": cid, "name": cname,
                "leads": leads, "opportunities": opps, "won": won_c,
                "revenue": round(revenue),
                "cost": round(cost),
                "cpl": round(cost / leads, 0) if leads and cost else None,
                "cpa": round(cost / won_deals, 0) if won_deals and cost else None,
                "roas": round(revenue / cost, 2) if cost else None,
            })
        campaigns.sort(key=lambda r: r["revenue"], reverse=True)

        total_spend = sum(c["cost"] for c in campaigns)
        attributed_revenue = sum(c["revenue"] for c in campaigns)
        total_won_deals = sum(c["won"] for c in campaigns)
        roi = {
            "total_spend": total_spend,
            "attributed_revenue": attributed_revenue,
            "roas": round(attributed_revenue / total_spend, 2) if total_spend else None,
            "net": attributed_revenue - total_spend,
            "cpl": round(total_spend / new_leads, 0) if new_leads and total_spend else None,
            "cac": round(total_spend / total_won_deals, 0) if total_won_deals and total_spend else None,
            "won_deals": total_won_deals,
        }

        return {
            "company": self.env.company.name,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "period": period,
            "pipeline": {
                "open": open_count,
                "pipeline_value": round(pipeline_value),
                "weighted_value": round(weighted_value),
                "won": won, "lost": lost,
                "win_rate": win_rate,
                "avg_deal": avg_deal,
                "new_leads": new_leads, "new_won": new_won,
            },
            "by_stage": by_stage,
            "by_source": by_source,
            "by_owner": by_owner,
            "aging": aging,
            "trend": trend,
            "buyers": buyers,
            "campaigns": campaigns,
            "roi": roi,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Drill-downs
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def open_records(self, kind, params=None):
        params = params or {}
        Lead = self.env["crm.lead"]

        def lead_action(name, domain):
            return {
                "type": "ir.actions.act_window",
                "name": name, "res_model": "crm.lead",
                "view_mode": "list,kanban,form",
                "domain": domain,
                "context": {"create": False}, "target": "current",
            }

        won_ids = self._won_stage_ids()
        if kind == "open":
            return lead_action(_("Open Opportunities"), [("active", "=", True)])
        if kind == "won":
            return lead_action(_("Won"), [("stage_id", "in", won_ids)])
        if kind == "lost":
            return lead_action(_("Lost"), ["|", ("active", "=", False), ("probability", "=", 0)])
        if kind == "stage":
            sid = params.get("id")
            dom = [("active", "=", True)]
            dom.append(("stage_id", "=", sid) if sid else ("stage_id", "=", False))
            return lead_action(_("Stage"), dom)
        if kind == "source":
            sid = params.get("id")
            dom = [("active", "=", True)]
            dom.append(("source_id", "=", sid) if sid else ("source_id", "=", False))
            return lead_action(_("Source"), dom)
        if kind == "owner":
            uid = params.get("id")
            dom = [("active", "=", True)]
            dom.append(("user_id", "=", uid) if uid else ("user_id", "=", False))
            return lead_action(_("Owner"), dom)
        if kind == "aging":
            bucket = params.get("bucket", "0-7d")
            low, high = {"0-7d": (0, 7), "8-30d": (8, 30),
                         "31-60d": (31, 60), "60d+": (61, None)}.get(bucket, (0, 7))
            today = fields.Date.context_today(self)
            dom = [("active", "=", True), ("date_last_stage_update", "!=", False)]
            if high:
                dom.append(("date_last_stage_update", ">=", fields.Datetime.to_string(
                    datetime.combine(today - timedelta(days=high), datetime.min.time()))))
            dom.append(("date_last_stage_update", "<=", fields.Datetime.to_string(
                datetime.combine(today - timedelta(days=low), datetime.max.time()))))
            return lead_action(_("Aging: %s") % bucket, dom)
        if kind == "campaign":
            cid = params.get("id")
            return lead_action(
                _("Campaign Leads"),
                [("campaign_id", "=", cid)] if cid else [("campaign_id", "=", False)])
        if kind == "campaign_revenue":
            cid = params.get("id")
            return {
                "type": "ir.actions.act_window",
                "name": _("Attributed Revenue"),
                "res_model": "sale.contract",
                "view_mode": "list,form",
                "domain": [("lead_id.campaign_id", "=", cid)] if cid
                          else [("lead_id", "!=", False)],
                "context": {"create": False}, "target": "current",
            }
        if kind == "buyers":
            return lead_action(_("Potential Buyers"), [("active", "=", True)])
        raise UserError(_("Unknown dashboard drill-down: %s") % kind)
