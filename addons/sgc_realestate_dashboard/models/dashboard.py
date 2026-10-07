# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
from datetime import datetime, timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Contract states that mean "the unit is sold / deal won". The tenant's bulk
# history uses the base ``signed`` state; the EOI workflow uses ``spa_signed`` /
# ``completed``. Treat all three as sold.
SIGNED_STATES = ("signed", "spa_signed", "completed")
# Live, in-funnel states (not yet sold, not dead).
OPEN_CONTRACT_STATES = ("eoi", "booked", "confirmed", "spa_issued")
DEAD_CONTRACT_STATES = ("cancelled", "refunded")
ALL_VALUE_STATES = SIGNED_STATES + OPEN_CONTRACT_STATES


class SgcRealEstateDashboard(models.AbstractModel):
    """Server side of the SGC real-estate dashboard. All figures are aggregated
    live from real records; every card can drill down to the exact list."""
    _name = "sgc.realestate.dashboard"
    _description = "SGC Real Estate Dashboard"

    # ─────────────────────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def _stage_map(self):
        Stage = self.env["crm.stage"]

        def pick(*names):
            for name in names:
                stage = Stage.search([("name", "=", name)], limit=1)
                if stage:
                    return stage
            return Stage.browse()

        return {
            "note": pick("Proposition", "Proposal", "Qualified").id or False,
            "won": Stage.search([("is_won", "=", True)]).ids,
        }

    @api.model
    def _group_counts(self, model, domain, groupby):
        # Odoo 17+ API (_read_group); read_group is a deprecated shim that logs
        # a stack trace on every call.
        rows = self.env[model].sudo()._read_group(domain, groupby, ["id:count"])
        out = {}
        for key, count in rows:
            out[key[0] if isinstance(key, (list, tuple)) else key] = count
        return out

    # ─────────────────────────────────────────────────────────────────────
    # Data feed
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def get_dashboard_data(self):
        cr = self.env.cr
        Property = self.env["property.details"].sudo()

        # ── Inventory ────────────────────────────────────────────────────
        unit_states = self._group_counts(
            "property.details", [], ["state"])
        units = {
            "total": sum(unit_states.values()),
            "available": unit_states.get("available", 0),
            "booked": unit_states.get("booked", 0),
            "sold": unit_states.get("sold", 0),
            "eoi": unit_states.get("eoi", 0),
        }

        # ── Contracts by state ───────────────────────────────────────────
        contract_states = self._group_counts("sale.contract", [], ["state"])
        contracts = {
            "total": sum(contract_states.values()),
            "eoi": contract_states.get("eoi", 0),
            "booked": contract_states.get("booked", 0),
            "confirmed": contract_states.get("confirmed", 0),
            "spa_issued": contract_states.get("spa_issued", 0),
            "signed": sum(contract_states.get(s, 0) for s in SIGNED_STATES),
            "cancelled": sum(contract_states.get(s, 0) for s in DEAD_CONTRACT_STATES),
        }

        # ── Money: sales value / collected / outstanding ─────────────────
        cr.execute("""
            SELECT COALESCE(SUM(sale_price), 0)
              FROM sale_contract
             WHERE state IN %s
        """, (ALL_VALUE_STATES,))
        sales_value = float(cr.fetchone()[0] or 0.0)

        cr.execute("""
            SELECT COALESCE(SUM(sale_price), 0)
              FROM sale_contract
             WHERE state IN %s
        """, (SIGNED_STATES,))
        signed_value = float(cr.fetchone()[0] or 0.0)

        cr.execute("""
            SELECT COALESCE(SUM(amount), 0)
              FROM sale_contract_installment
             WHERE state = 'paid'
        """)
        collected = float(cr.fetchone()[0] or 0.0)
        outstanding = max(sales_value - collected, 0.0)
        collection_rate = round(collected / sales_value * 100.0, 1) if sales_value else 0.0

        # ── Escrow ───────────────────────────────────────────────────────
        cr.execute("""
            SELECT COALESCE(SUM(required_amount), 0),
                   COALESCE(SUM(allocated_amount), 0)
              FROM escrow_allocation
             WHERE active = true
        """)
        esc_required, esc_allocated = (float(x or 0.0) for x in cr.fetchone())
        escrow = {
            "required": esc_required,
            "allocated": esc_allocated,
            "shortfall": esc_allocated - esc_required,
            "funded_pct": round(esc_allocated / esc_required * 100.0, 1) if esc_required else 0.0,
        }

        # ── Journey funnel ───────────────────────────────────────────────
        Lead = self.env["crm.lead"].sudo()
        funnel = {
            "leads": Lead.search_count([]),
            "open_opportunities": Lead.search_count([("active", "=", True)]),
            "eoi": contracts["eoi"],
            "booked": contracts["booked"] + contracts["confirmed"],
            "spa_signed": contracts["signed"],
        }

        # ── Pipeline aging (open, active leads) ──────────────────────────
        cr.execute("""
            SELECT
              COALESCE(SUM(CASE WHEN (CURRENT_DATE - date_last_stage_update::date) BETWEEN 0 AND 7  THEN 1 ELSE 0 END), 0) AS b0,
              COALESCE(SUM(CASE WHEN (CURRENT_DATE - date_last_stage_update::date) BETWEEN 8 AND 30 THEN 1 ELSE 0 END), 0) AS b1,
              COALESCE(SUM(CASE WHEN (CURRENT_DATE - date_last_stage_update::date) BETWEEN 31 AND 60 THEN 1 ELSE 0 END), 0) AS b2,
              COALESCE(SUM(CASE WHEN (CURRENT_DATE - date_last_stage_update::date) > 60 THEN 1 ELSE 0 END), 0) AS b3
              FROM crm_lead
             WHERE active = true AND date_last_stage_update IS NOT NULL
        """)
        b0, b1, b2, b3 = (int(x or 0) for x in cr.fetchone())
        aging = [
            {"bucket": "0-7d", "count": b0},
            {"bucket": "8-30d", "count": b1},
            {"bucket": "31-60d", "count": b2},
            {"bucket": "60d+", "count": b3},
        ]

        # ── Project breakdown (units / sold / value) ─────────────────────
        cr.execute("""
            SELECT COALESCE(pj.name, 'Unassigned') AS project,
                   COUNT(pd.id) AS units,
                   COUNT(pd.id) FILTER (WHERE pd.state = 'sold') AS sold
              FROM property_details pd
              LEFT JOIN property_project pj ON pj.id = pd.project_id
             GROUP BY pj.name
             ORDER BY units DESC
        """)
        projects = [
            {"project": r[0], "units": r[1], "sold": r[2]}
            for r in cr.fetchall()
        ]

        # ── Leads by source ──────────────────────────────────────────────
        cr.execute("""
            SELECT COALESCE(NULLIF(s.name, ''), 'Unassigned') AS source,
                   COUNT(l.id) AS cnt
              FROM crm_lead l
              LEFT JOIN utm_source s ON s.id = l.source_id
             GROUP BY 1
             ORDER BY cnt DESC
             LIMIT 8
        """)
        sources = [{"source": r[0], "count": r[1]} for r in cr.fetchall()]

        return {
            "company": self.env.company.name,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "units": units,
            "contracts": contracts,
            "money": {
                "sales_value": sales_value,
                "signed_value": signed_value,
                "collected": collected,
                "outstanding": outstanding,
                "collection_rate": collection_rate,
            },
            "escrow": escrow,
            "funnel": funnel,
            "aging": aging,
            "projects": projects,
            "sources": sources,
        }

    # ─────────────────────────────────────────────────────────────────────
    # Drill-down: the records behind every number
    # ─────────────────────────────────────────────────────────────────────
    @api.model
    def open_records(self, kind, params=None):
        params = params or {}

        def act(name, model, domain, view_mode="list,form"):
            return {
                "type": "ir.actions.act_window",
                "name": name,
                "res_model": model,
                "view_mode": view_mode,
                "domain": domain,
                "context": {"create": False},
                "target": "current",
            }

        if kind == "units":
            state = params.get("state")
            dom = [("state", "=", state)] if state else []
            return act(_("Units"), "property.details", dom)
        if kind == "contracts":
            state = params.get("state")
            dom = [("state", "=", state)] if state else []
            return act(_("Sale Contracts"), "sale.contract", dom)
        if kind == "contracts_signed":
            return act(_("Signed Contracts"), "sale.contract",
                       [("state", "in", SIGNED_STATES)])
        if kind == "contracts_open":
            return act(_("Open Contracts"), "sale.contract",
                       [("state", "in", OPEN_CONTRACT_STATES)])
        if kind == "collected":
            return act(_("Paid Installments"), "sale.contract.installment",
                       [("state", "=", "paid")])
        if kind == "outstanding":
            return act(_("Outstanding Contracts"), "sale.contract",
                       [("state", "in", ALL_VALUE_STATES)])
        if kind == "escrow":
            return act(_("Escrow Allocations"), "escrow.allocation", [])
        if kind == "leads":
            return act(_("Leads & Opportunities"), "crm.lead", [])
        if kind == "opportunities":
            return act(_("Open Opportunities"), "crm.lead",
                       [("active", "=", True)])
        if kind == "aging":
            bucket = params.get("bucket", "0-7d")
            low, high = {
                "0-7d": (0, 7), "8-30d": (8, 30),
                "31-60d": (31, 60), "60d+": (61, None),
            }.get(bucket, (0, 7))
            today = fields.Date.context_today(self)
            dom = [("active", "=", True), ("date_last_stage_update", "!=", False)]
            dom.append(("date_last_stage_update", ">=", fields.Datetime.to_string(
                datetime.combine(today - timedelta(days=high if high else 3650),
                                 datetime.min.time()))))
            if high:
                dom.append(("date_last_stage_update", "<=", fields.Datetime.to_string(
                    datetime.combine(today - timedelta(days=low), datetime.max.time()))))
            else:
                dom.append(("date_last_stage_update", "<=", fields.Datetime.to_string(
                    datetime.combine(today - timedelta(days=low), datetime.max.time()))))
            return act(_("Pipeline Aging: %s", bucket), "crm.lead", dom)
        if kind == "project":
            name = params.get("project")
            dom = [("project_id.name", "=", name)] if name and name != "Unassigned" else (
                [("project_id", "=", False)] if name == "Unassigned" else [])
            return act(_("Units: %s", name), "property.details", dom)

        raise UserError(_("Unknown dashboard drill-down: %s") % kind)
