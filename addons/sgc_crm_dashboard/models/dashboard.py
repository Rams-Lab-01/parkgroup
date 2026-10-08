from odoo import models, api, fields, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
from collections import OrderedDict

import psycopg2


class CRMDashboard(models.AbstractModel):
    _name = "crm.dashboard"
    _description = "CRM Dashboard"

    @api.model
    def _is_admin(self):
        """Check if current user has admin/manager access."""
        user = self.env.user
        admin_groups = [
            self.env.ref("base.group_system", raise_if_not_found=False),
            self.env.ref("sales_team.group_sale_manager", raise_if_not_found=False),
        ]
        for g in admin_groups:
            if g and g in user.group_ids:
                return True
        # Fallback: check for common admin group names
        cr = self.env.cr
        cr.execute("""
            SELECT 1 FROM res_groups_users_rel ug
            JOIN res_groups g ON g.id = ug.gid
            WHERE ug.uid = %s AND (
                g.id IN (SELECT id FROM res_groups WHERE name->>'en_US' IN ('Administrator', 'Admin', 'Role / Administrator'))
            )
            LIMIT 1
        """, (user.id,))
        return cr.fetchone() is not None

    @api.model
    def _scope(self, user_id, date_range=None):
        """(is_admin, target_ids, lead_domain_base) for the given salesperson
        filter. Shared by get_dashboard_data (to compute the numbers) and
        open_records (to compute the domain behind a click) so the two can
        never silently diverge — the count shown and the list it opens must
        always describe the same records.

        date_range, if provided, is a string like "30d" or "custom_start,custom_end"
        applied uniformly across all KPI queries so the clicked list always
        matches what's on screen.
        """
        is_admin = self._is_admin()
        current_user = self.env.user

        if user_id:
            target_users = self.env["res.users"].browse(user_id)
        elif is_admin:
            target_users = self.env["res.users"].search([("id", ">", 2)])
        else:
            target_users = current_user

        target_ids = target_users.ids

        lead_domain_base = [("user_id", "in", target_ids)] if not user_id and not is_admin else []
        if user_id:
            lead_domain_base = [("user_id", "=", user_id)]

        # Build date-range filter, applied uniformly across every KPI query
        date_filter = ""
        date_params = []
        if date_range:
            if date_range == "today":
                date_filter = "AND l.create_date >= CURRENT_DATE"
            elif date_range == "7d":
                date_filter = "AND l.create_date >= CURRENT_DATE - INTERVAL '6 days'"
            elif date_range == "30d":
                date_filter = "AND l.create_date >= CURRENT_DATE - INTERVAL '29 days'"
            elif date_range == "90d":
                date_filter = "AND l.create_date >= CURRENT_DATE - INTERVAL '89 days'"
            elif date_range == "6m":
                date_filter = "AND l.create_date >= CURRENT_DATE - INTERVAL '179 days'"
            elif date_range == "12m":
                date_filter = "AND l.create_date >= CURRENT_DATE - INTERVAL '364 days'"
            elif "," in date_range:
                # "start,end" ISO dates; validated, then bound as parameters (never interpolated)
                try:
                    start_s, end_s = (fields.Date.to_date(x.replace("custom", "").strip("_")).isoformat()
                                      for x in date_range.split(",", 1))
                    date_filter = "AND l.create_date >= %s AND l.create_date < (%s::date + 1)"
                    date_params = [start_s, end_s]
                except Exception:
                    pass  # gracefully fall back to no date filter

        return is_admin, target_ids, lead_domain_base, date_filter, date_params

    @api.model
    def _stage_map(self):
        """Resolve the dashboard's semantic pipeline stages by NAME against
        the stages that actually exist in THIS database, instead of hardcoding
        numeric ``crm.stage`` ids. This keeps the module portable across
        tenants: a tenant with a richer pipeline (Research Done / Email
        Outreach / Meeting Booked ...) and one with a simpler one
        (New / Qualified / Proposition / Won) both work, and every KPI whose
        stage is absent simply degrades to 0 rather than raising.

        Alias lists map a tenant's native stage onto the dashboard card that
        means the same thing:
            research_done  <- "Research Done"  | "Qualified"
            meeting_booked <- "Meeting Booked" | "Proposition" | "Proposal"
            outreach_email <- "Valid Contact"  | "Email Outreach" | "Outreach"
            follow_up      <- "Follow Up"      | "Follow-up"
        """
        Stage = self.env["crm.stage"]

        def pick(*names):
            for name in names:
                stage = Stage.search([("name", "=", name)], limit=1)
                if stage:
                    return stage
            return Stage.browse()

        ordered = Stage.search([], order="sequence, id")
        new_stage = ordered[:1] if ordered else Stage.browse()
        return {
            "new": new_stage.id or False,
            "research_done": pick("Research Done", "Qualified").id or False,
            "outreach_email": pick("Valid Contact", "Email Outreach", "Outreach").id or False,
            "meeting_booked": pick("Meeting Booked", "Proposition", "Proposal").id or False,
            "follow_up": pick("Follow Up", "Follow-up").id or False,
            "dead": Stage.search(
                [("name", "in", ["No Answer", "Not Interested", "Lost"])]
            ).ids,
            "won": Stage.search([("is_won", "=", True)]).ids,
        }

    @api.model
    def get_dashboard_data(self, user_id=None, date_range=None):
        lead = self.env["crm.lead"]
        order = self.env["sale.order"]
        team = self.env["crm.team"]
        cr = self.env.cr
        # JIT compilation adds ~1s to several dashboard queries for no benefit
        # once the targeted indexes are in place; disable it for this request.
        try:
            cr.execute("SET LOCAL jit = off")
        except psycopg2.Error:
            pass

        is_admin, target_ids, lead_domain_base, date_filter, date_params = self._scope(user_id, date_range)
        current_user = self.env.user

        # Get won stage ids dynamically from CRM stages
        won_stage_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
        won_stage_condition = f"l.stage_id IN ({','.join(map(str, won_stage_ids))})" if won_stage_ids else "1=0"

        # Semantic stages resolved against this DB's real pipeline (portable).
        sm = self._stage_map()

        def _stage_count(stage_id):
            """Active leads in a resolved stage, honouring the salesperson
            filter. Returns 0 when the tenant has no such stage."""
            if not stage_id:
                return 0
            dom = [("active", "=", True), ("stage_id", "=", stage_id)]
            if user_id:
                dom.append(("user_id", "=", user_id))
            elif not is_admin:
                dom.append(("user_id", "in", target_ids))
            return lead.search_count(dom)

        # Apply the selected date window as an ORM domain for the core counts.
        # (date_filter/date_params are SQL fragments for the raw-SQL helpers;
        #  the ORM search_count calls below need a real Odoo domain.)
        date_domain = self._date_range_domain(date_range)
        base = (lead_domain_base or []) + date_domain
        total_leads = lead.search_count(base)
        pipeline = lead.search_count(base + [("active", "=", True), ("probability", ">", 0), ("probability", "<", 100)])
        won = lead.search_count(base + [("stage_id", "in", won_stage_ids)])
        lost = lead.search_count(base + ["|", ("active", "=", False), ("probability", "=", 0)])

        fu_user_filter, fu_params = "", []
        if user_id:
            fu_user_filter, fu_params = "AND l.user_id = %s", [user_id]
        elif not is_admin:
            fu_user_filter, fu_params = "AND l.user_id IN %s", [tuple(target_ids)]

        # Apply date range filter if specified to user-filtered queries
        if date_filter:
            fu_user_filter = fu_user_filter + date_filter
            if date_params:
                fu_params = fu_params + date_params

        # Stage-flow KPIs resolved by name (see _stage_map). Absent stages -> 0.
        follow_up = _stage_count(sm["follow_up"])
        research_done = _stage_count(sm["research_done"])
        outreach_email = _stage_count(sm["outreach_email"])
        booked = _stage_count(sm["meeting_booked"])

        # Daily Activity: leads with any real activity today
        # (write_date change OR mail_message OR activity done OR stage change).
        # Use EXISTS + half-open timestamp ranges so PostgreSQL can use indexes
        # instead of casting every row to date (the old query timed out at ~200s).
        cr.execute(f"""
            SELECT COUNT(DISTINCT l.id)
            FROM crm_lead l
            WHERE (
                (l.write_date >= CURRENT_DATE AND l.write_date < CURRENT_DATE + INTERVAL '1 day')
                OR EXISTS (
                    SELECT 1 FROM mail_message m
                    WHERE m.res_id = l.id AND m.model = 'crm.lead'
                      AND m.date >= CURRENT_DATE
                      AND m.date < CURRENT_DATE + INTERVAL '1 day'
                )
                OR EXISTS (
                    SELECT 1 FROM mail_activity a
                    WHERE a.res_id = l.id AND a.res_model = 'crm.lead'
                      AND a.date_done >= CURRENT_DATE
                      AND a.date_done < CURRENT_DATE + INTERVAL '1 day'
                )
                OR EXISTS (
                    SELECT 1 FROM mail_tracking_value tv
                    JOIN mail_message m2 ON m2.id = tv.mail_message_id
                    WHERE m2.res_id = l.id AND m2.model = 'crm.lead'
                      AND tv.create_date >= CURRENT_DATE
                      AND tv.create_date < CURRENT_DATE + INTERVAL '1 day'
                )
            )
              {fu_user_filter}
        """, fu_params)
        daily_activity = cr.fetchone()[0] or 0

        # Scope every order-side KPI to the active user filter.
        # Admin without user_id: ALL orders (overall revenue).
        # Admin with user_id, or non-admin SDR: only that salesperson's orders.
        order_user_filter = []
        if user_id:
            order_user_filter = [("user_id", "=", user_id)]
        elif not is_admin:
            order_user_filter = [("user_id", "in", target_ids)]

        total_orders = order.search_count(order_user_filter)
        confirmed_orders = order.search_count(order_user_filter + [("state", "=", "sale")])
        if user_id:
            rev_params = [user_id]
            rev_user_sql = " AND user_id = %s"
        elif not is_admin:
            rev_params = [tuple(target_ids)]
            rev_user_sql = " AND user_id IN %s"
        else:
            rev_params = []
            rev_user_sql = ""
        cr.execute(
            "SELECT COALESCE(SUM(amount_total), 0) FROM sale_order WHERE state = 'sale'"
            + rev_user_sql,
            rev_params,
        )
        confirmed_revenue = round(cr.fetchone()[0] or 0, 2)

        # Proposal pipeline: amount_total of quotations (draft + sent).
        # "Converted to sales" is confirmed_revenue above. The PROPOSAL/REVENUE
        # card renders both as `proposal / converted` with K/M/B abbreviation.
        # Same scope rule as confirmed_revenue.
        cr.execute(
            "SELECT COALESCE(SUM(amount_total), 0) FROM sale_order WHERE state IN ('draft', 'sent')"
            + rev_user_sql,
            rev_params,
        )
        revenue_proposal = round(cr.fetchone()[0] or 0, 2)
        revenue_converted = confirmed_revenue

        # ─── Stage-flow KPIs (the New-stage pipeline monitor) ────────────
        # 1) New Leads Today: leads created today (they enter the
        #    "New" stage by default). This is the input side.
        # 2) Moved Out of New Today: leads that were moved OUT of the
        #    "New" stage today. The user wants to monitor whether the
        #    team is working the top-of-funnel backlog. We approximate
        #    via write_date::date = today AND current stage != New.
        new_stage_id = sm["new"]  # first stage by sequence (tenant-native "New")
        # NEW LEADS TODAY now means: count of active leads currently sitting in
        # the "New" stage. Scoped to the active user filter so the dropdown
        # refetches it on filter change.
        new_leads_domain = [("active", "=", True)]
        if new_stage_id:
            new_leads_domain.append(("stage_id", "=", new_stage_id))
        if user_id:
            new_leads_domain.append(("user_id", "=", user_id))
        elif not is_admin:
            new_leads_domain.append(("user_id", "in", target_ids))
        new_leads_today = lead.search_count(new_leads_domain)
        moved_out_of_new_today = 0
        if new_stage_id:
            moved_user_filter = ""
            moved_params = []
            if user_id:
                moved_user_filter = "AND l.user_id = %s"
                moved_params.append(user_id)
            elif not is_admin:
                moved_user_filter = "AND l.user_id IN %s"
                moved_params.append(tuple(target_ids))
            if date_filter:
                moved_user_filter = moved_user_filter + date_filter
                if date_params:
                    moved_params = moved_params + date_params
            cr.execute(f"""
                SELECT COUNT(*)
                FROM crm_lead l
                WHERE l.active = true
                  AND l.stage_id != %s
                  AND l.write_date::date = CURRENT_DATE
                  {moved_user_filter}
            """, [new_stage_id] + moved_params)
            moved_out_of_new_today = cr.fetchone()[0] or 0

        # Funnel + Pipeline stages: single GROUP BY instead of one search_count
        # per stage. Count active leads to match the implicit active_test the
        # old ORM search_count applied.
        lang = self.env.user.lang or 'en_US'
        stage_user_filter = ""
        stage_params = []
        if user_id:
            stage_user_filter = "AND l.user_id = %s"
            stage_params = [user_id]
        elif not is_admin:
            stage_user_filter = "AND l.user_id IN %s"
            stage_params = [tuple(target_ids)]
        # Add date range filter if provided
        if date_filter:
            stage_user_filter = stage_user_filter + date_filter
            if date_params:
                stage_params = stage_params + date_params

        cr.execute(f"""
            SELECT s.id, s.name->>%s AS name,
                   COUNT(l.id) FILTER (WHERE l.active = true) AS funnel_count,
                   COUNT(l.id) FILTER (WHERE l.active = true) AS stage_count
            FROM crm_stage s
            LEFT JOIN crm_lead l ON l.stage_id = s.id {stage_user_filter}
            GROUP BY s.id, s.name, s.sequence
            ORDER BY s.sequence
        """, (lang,) + tuple(stage_params))
        funnel_rows = cr.dictfetchall()
        funnel_stages = [{"name": r["name"], "count": r["funnel_count"]} for r in funnel_rows]
        stages = [{"name": r["name"], "count": r["stage_count"]} for r in funnel_rows if r["stage_count"] > 0]

        # ─── Pipeline Aging (replace Conversion Funnel insight) ─────────
        # Age = days since create_date. Buckets surface how much of the
        # open pipeline is rotting vs. fresh.
        aging_domain = [("active", "=", True)]
        if user_id:
            aging_domain.append(("user_id", "=", user_id))
        elif not is_admin:
            aging_domain.append(("user_id", "in", target_ids))
        aging_user_filter = ""
        aging_params = []
        if user_id:
            aging_user_filter = "AND l.user_id = %s"
            aging_params.append(user_id)
        elif not is_admin:
            aging_user_filter = "AND l.user_id IN %s"
            aging_params.append(tuple(target_ids))
        if date_filter:
            aging_user_filter = aging_user_filter + date_filter
            if date_params:
                aging_params = aging_params + date_params
        cr.execute("""
            SELECT
              SUM(CASE WHEN (CURRENT_DATE - create_date::date) BETWEEN 0 AND 7 THEN 1 ELSE 0 END) AS b_0_7,
              SUM(CASE WHEN (CURRENT_DATE - create_date::date) BETWEEN 8 AND 30 THEN 1 ELSE 0 END) AS b_8_30,
              SUM(CASE WHEN (CURRENT_DATE - create_date::date) BETWEEN 31 AND 60 THEN 1 ELSE 0 END) AS b_31_60,
              SUM(CASE WHEN (CURRENT_DATE - create_date::date) BETWEEN 61 AND 90 THEN 1 ELSE 0 END) AS b_61_90,
              SUM(CASE WHEN (CURRENT_DATE - create_date::date) > 90 THEN 1 ELSE 0 END) AS b_90p
            FROM crm_lead l WHERE l.active = true
              """ + aging_user_filter + """
        """, tuple(aging_params))
        row = cr.dictfetchone() or {}
        pipeline_aging = [
            {"bucket": "0-7d",   "count": row.get("b_0_7") or 0},
            {"bucket": "8-30d",  "count": row.get("b_8_30") or 0},
            {"bucket": "31-60d", "count": row.get("b_31_60") or 0},
            {"bucket": "61-90d", "count": row.get("b_61_90") or 0},
            {"bucket": "90d+",   "count": row.get("b_90p") or 0},
        ]

        # ─── Pipeline by Owner (concentration insight) ───────────────────
        owner_filter = ""
        owner_params = []
        if user_id:
            owner_filter = "AND l.user_id = %s"
            owner_params.append(user_id)
        elif not is_admin:
            owner_filter = "AND l.user_id IN %s"
            owner_params.append(tuple(target_ids))
        if date_filter:
            owner_filter = owner_filter + date_filter
            if date_params:
                owner_params = owner_params + date_params
        cr.execute("""
            SELECT u.id as user_id, COALESCE(p.name, u.login) as name,
                   COUNT(l.id) as active_leads
            FROM res_users u
            LEFT JOIN res_partner p ON u.partner_id = p.id
            JOIN crm_lead l ON l.user_id = u.id AND l.active = true
            WHERE u.active = true AND u.id > 2
              """ + owner_filter + """
            GROUP BY u.id, p.name, u.login
            HAVING COUNT(l.id) > 0
            ORDER BY active_leads DESC
            LIMIT 10
        """, owner_params)
        owner_pipeline = [
            {"id": r["user_id"], "name": r["name"], "count": r["active_leads"]}
            for r in cr.dictfetchall()
        ]

        # ─── Pipeline by Source (replaces meaningless Teams widget) ──────
        # NOTE: utm_source.name is varchar (not jsonb like crm_stage.name),
        # so do NOT use the ->> operator — read it directly.
        source_params = []
        source_user_filter = ""
        if user_id:
            source_user_filter = "AND l.user_id = %s"
            source_params.append(user_id)
        elif not is_admin:
            source_user_filter = "AND l.user_id IN %s"
            source_params.append(tuple(target_ids))
        if date_filter:
            source_user_filter = source_user_filter + date_filter
            if date_params:
                source_params = source_params + date_params
        cr.execute("""
            SELECT
              COALESCE(NULLIF(s.name, ''), 'Unassigned') as source_name,
              COUNT(l.id) as cnt
            FROM crm_lead l
            LEFT JOIN utm_source s ON l.source_id = s.id
            WHERE l.active = true
              """ + source_user_filter + """
            GROUP BY source_name
            ORDER BY cnt DESC
            LIMIT 10
        """, tuple(source_params))
        pipeline_by_source = [
            {"name": r["source_name"] or "Unassigned", "count": r["cnt"]}
            for r in cr.dictfetchall()
        ]
        # If everything is "Unassigned", drop the breakdown — it's noise.
        if pipeline_by_source and pipeline_by_source[0]["name"] == "Unassigned" and len(pipeline_by_source) == 1:
            pipeline_by_source = []

        # ─── Qualification & Gate Compliance (sgc_sales_playbook) ────────
        # gate_pass_rate / stalled_deals_count / objection_conversion_rate
        # need x_gate_status / sgc.lead.objection, which only exist once
        # sgc_sales_playbook is installed (stalled_deals_count itself reads
        # only stock date_last_stage_update, but is gated the same way for
        # consistency with the rest of this panel) — this dashboard
        # doesn't depend on that module, so gate on its install state rather
        # than assuming the fields/model are present.
        sgc_playbook_installed = bool(self.env["ir.module.module"].sudo().search_count([
            ("name", "=", "sgc_sales_playbook"), ("state", "=", "installed"),
        ]))
        gate_pass_rate = None
        gate_pass_rate_n = 0
        gate_pass_rate_ai = None
        gate_pass_rate_ai_n = 0
        gate_pass_rate_human = None
        gate_pass_rate_human_n = 0
        stalled_deals_count = None
        objection_conversion_rate = None
        objection_conversion_rate_n = 0
        gate_stage_configured = True
        if sgc_playbook_installed:
            # Surface a misconfigured gate_stage_id here rather than let the
            # gate fail open silently in crm_lead.py — reps would otherwise
            # have no visibility that Proposal-stage qualification isn't
            # actually being enforced.
            gate_stage_configured = bool(lead._get_gate_stage())

            # gate_pass_rate: % of deals at/after Meeting Booked (stage
            # sequence >= 7) with all 4 Verifiable Buyer Exit Criteria
            # answered right now. Numerator: x_gate_status == 'qualified'.
            # Denominator: all such deals, active only, respecting the
            # current salesperson filter. Window: point-in-time snapshot —
            # there is no historical gate-pass table, so this is not a
            # date-ranged rate. Excludes non-opportunity leads and archived
            # deals. None (not 0%) when the denominator is 0, so the UI can
            # tell "no gateable deals yet" apart from "0% pass rate" — at
            # n=4-5 (current Meeting Booked/Proposal volume) one record
            # swings the percentage 20-25 points, so a bare number without
            # n= is actively misleading (S5).
            gateable_domain = (lead_domain_base or []) + [
                ("active", "=", True), ("stage_id.sequence", ">=", 7),
            ]
            gate_pass_rate_n = lead.search_count(gateable_domain)
            if gate_pass_rate_n:
                qualified = lead.search_count(gateable_domain + [("x_gate_status", "=", "qualified")])
                gate_pass_rate = round(qualified / gate_pass_rate_n * 100.0, 1)

                # Split by provenance: were the 4 answers typed by the rep,
                # or copied from an AI transcript summary (sgc_meeting_ai)?
                # A gate that passes mostly on AI-inferred answers isn't
                # measuring discovery discipline the way a rep-typed answer
                # does. 'ai' = at least one of the 4 fields is AI-confirmed;
                # 'human' = all 4 are manual — see
                # crm.lead._get_gate_provenance_domain() for why these
                # partition cleanly.
                ai_domain = gateable_domain + lead._get_gate_provenance_domain("ai")
                human_domain = gateable_domain + lead._get_gate_provenance_domain("human")
                gate_pass_rate_ai_n = lead.search_count(ai_domain)
                if gate_pass_rate_ai_n:
                    ai_qualified = lead.search_count(ai_domain + [("x_gate_status", "=", "qualified")])
                    gate_pass_rate_ai = round(ai_qualified / gate_pass_rate_ai_n * 100.0, 1)
                gate_pass_rate_human_n = lead.search_count(human_domain)
                if gate_pass_rate_human_n:
                    human_qualified = lead.search_count(human_domain + [("x_gate_status", "=", "qualified")])
                    gate_pass_rate_human = round(human_qualified / gate_pass_rate_human_n * 100.0, 1)

            # stalled_deals_count: active opportunities (any stage, current
            # salesperson filter applied) whose date_last_stage_update is
            # 21+ days old. Always a raw count, not a percentage — no
            # denominator to guard.
            stall_cutoff = fields.Datetime.to_string(datetime.now() - timedelta(weeks=3))
            stalled_deals_count = lead.search_count((lead_domain_base or []) + [
                ("active", "=", True),
                ("date_last_stage_update", "!=", False),
                ("date_last_stage_update", "<=", stall_cutoff),
            ])

            # objection_conversion_rate: % of sgc.lead.objection records
            # (all-time, current salesperson filter applied) where
            # resulted_in_meeting is True. Numerator: resulted_in_meeting
            # == True. Denominator: all logged objections. Excludes
            # nothing else — every objection a rep logs counts. None when
            # 0 objections logged, same N/A-vs-0% reasoning as above.
            Objection = self.env["sgc.lead.objection"].sudo()
            obj_domain = [("lead_id.user_id", "in", target_ids)] if (not user_id and not is_admin) else (
                [("lead_id.user_id", "=", user_id)] if user_id else []
            )
            objection_conversion_rate_n = Objection.search_count(obj_domain)
            if objection_conversion_rate_n:
                won_objections = Objection.search_count(obj_domain + [("resulted_in_meeting", "=", True)])
                objection_conversion_rate = round(
                    won_objections / objection_conversion_rate_n * 100.0, 1
                )

        # Stale-lead count: parked 30+ days in a dead/lost stage with no
        # lost_reason_id ever set. Dead stages are resolved by name; if the
        # tenant has none, the metric is 0. Uses only stock crm.lead fields.
        stale_cutoff_dt = fields.Datetime.to_string(datetime.now() - timedelta(days=30))
        stale_lead_filter = ""
        stale_params = [stale_cutoff_dt]
        if user_id:
            stale_lead_filter = "AND user_id = %s"
            stale_params.append(user_id)
        elif not is_admin:
            stale_lead_filter = "AND user_id IN %s"
            stale_params.append(tuple(target_ids))
        if date_filter:
            stale_lead_filter = stale_lead_filter + date_filter
            if date_params:
                stale_params = stale_params + date_params
        dead_stage_ids = sm["dead"]
        if dead_stage_ids:
            dead_sql = ",".join(map(str, dead_stage_ids))
            cr.execute(f"""
                SELECT COUNT(*)
                FROM crm_lead
                WHERE active = true
                  AND stage_id IN ({dead_sql})
                  AND lost_reason_id IS NULL
                  AND write_date <= %s
                  {stale_lead_filter}
            """, stale_params)
            stale_lead_count = cr.fetchone()[0] or 0
        else:
            stale_lead_count = 0

        # Per-salesperson summary with days-since-booking
        cr = self.env.cr
        user_filter = ""
        params = []
        if user_id:
            user_filter = "AND l.user_id = %s"
            params = [user_id]
        elif not is_admin:
            user_filter = "AND l.user_id = %s"
            params = [current_user.id]
        # Add date range filter
        if date_filter:
            user_filter = user_filter + date_filter
            if date_params:
                params = params + date_params

        won_stage_ids_sql = ",".join(map(str, won_stage_ids)) if won_stage_ids else "0"

        cr.execute(f"""
            SELECT
                u.id as user_id,
                COALESCE(p.name, u.login) as name,
                count(l.id) as total,
                SUM(CASE WHEN l.active=true AND l.stage_id IN ({won_stage_ids_sql}) THEN 1 ELSE 0 END) as won,
                SUM(CASE WHEN l.active=false OR (l.active=true AND l.probability=0) THEN 1 ELSE 0 END) as lost,
                MAX(CASE WHEN l.active=true AND l.stage_id IN ({won_stage_ids_sql}) THEN l.date_closed END) as last_win_date,
                MAX(l.write_date) as last_activity_date,
                SUM(CASE WHEN l.create_date >= NOW() - INTERVAL '30 days' THEN 1 ELSE 0 END) as last_30d,
                SUM(CASE WHEN l.create_date >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) as last_7d
            FROM crm_lead l
            JOIN res_users u ON l.user_id = u.id
            LEFT JOIN res_partner p ON u.partner_id = p.id
            WHERE u.active = true AND u.id > 2 {user_filter}
            GROUP BY u.id, p.name, u.login
            ORDER BY total DESC
        """, params)
        salesperson_data = []
        for r in cr.dictfetchall():
            last_win = r["last_win_date"]
            last_act = r["last_activity_date"]
            now = datetime.now()
            if last_win:
                days_since_win = (now - last_win.replace(tzinfo=None)).days
            else:
                days_since_win = None
            if last_act:
                days_since_act = (now - last_act.replace(tzinfo=None)).days
            else:
                days_since_act = None
            # "Days without booking" = days since last win; if no wins, days since last activity
            days_without_booking = days_since_win if days_since_win is not None else days_since_act
            salesperson_data.append({
                "id": r["user_id"],
                "name": r["name"],
                "leads": r["total"],
                "won": r["won"],
                "lost": r["lost"],
                "last_30d": r["last_30d"],
                "last_7d": r["last_7d"],
                "days_since_win": days_since_win,
                "days_since_activity": days_since_act,
                "days_without_booking": days_without_booking,
            })

        # Monthly activity: last 6 months of created / won / archived.
        # date_closed is preferred over create_date because it tells us when
        # the deal actually moved, not when it was imported.
        monthly = []
        now = datetime.now()
        months = OrderedDict()
        for i in range(5, -1, -1):
            d = now - timedelta(days=30 * i)
            key = d.strftime("%Y-%m")
            months[key] = {"created": 0, "won": 0, "lost": 0}

        range_start = (now - timedelta(days=180)).strftime("%Y-%m-%d")
        month_user_filter = ""
        month_params = []
        if user_id:
            month_user_filter = "AND l.user_id = %s"
            month_params = [user_id]
        elif not is_admin:
            month_user_filter = "AND l.user_id IN %s"
            month_params = [tuple(target_ids)]
        if date_filter:
            month_user_filter = month_user_filter + date_filter
            if date_params:
                month_params = month_params + date_params

        cr.execute(f"""
            SELECT TO_CHAR(create_date, 'YYYY-MM') AS month, COUNT(*) AS cnt
            FROM crm_lead l
            WHERE l.active = true
              AND l.create_date >= %s
              {month_user_filter}
            GROUP BY TO_CHAR(create_date, 'YYYY-MM')
        """, [range_start] + month_params)
        for r in cr.dictfetchall():
            if r["month"] in months:
                months[r["month"]]["created"] = r["cnt"]

        won_stage_ids_tuple = tuple(won_stage_ids) if won_stage_ids else (0,)
        cr.execute(f"""
            SELECT TO_CHAR(date_closed, 'YYYY-MM') AS month,
                   SUM(CASE WHEN active = true AND stage_id IN %s THEN 1 ELSE 0 END) AS won,
                   SUM(CASE WHEN active = false THEN 1 ELSE 0 END) AS lost
            FROM crm_lead l
            WHERE l.date_closed >= %s
              {month_user_filter}
            GROUP BY TO_CHAR(date_closed, 'YYYY-MM')
        """, (won_stage_ids_tuple, range_start) + tuple(month_params))
        for r in cr.dictfetchall():
            if r["month"] in months:
                months[r["month"]]["won"] = r["won"] or 0
                months[r["month"]]["lost"] = r["lost"] or 0

        for k, v in months.items():
            monthly.append({"month": k, "created": v["created"], "won": v["won"], "lost": v["lost"]})

        # (Teams block removed — DB has only 1 team, no insight. Replaced
        # by owner_pipeline + pipeline_by_source above.)

        # All users for filter dropdown (admin only, exclude inactive)
        all_users = []
        if is_admin:
            for u in self.env["res.users"].search([("id", ">", 2), ("active", "=", True)]):
                all_users.append({"id": u.id, "name": u.partner_id.name or u.login})

        return {
            "is_admin": is_admin,
            "current_user_id": current_user.id,
            "all_users": all_users,
            "selected_user_id": user_id,
            "kpi": {
                "total_leads": total_leads,
                "pipeline": pipeline,
                "new_leads_today": new_leads_today,
                "moved_out_of_new_today": moved_out_of_new_today,
                "won": won,
                "lost": lost,
                "follow_up": follow_up,
                "research_done": research_done,
                "outreach_email": outreach_email,
                "booked": booked,
                "daily_activity": daily_activity,
                "total_orders": total_orders,
                "confirmed_orders": confirmed_orders,
                "confirmed_revenue": confirmed_revenue,
                "revenue_proposal": revenue_proposal,
                "revenue_converted": revenue_converted,
                # ─── Real Estate KPIs (P0) ──────────────────────────
                "conversion_rate": self._compute_conversion_rate(
                    won, lost, pipeline),
                "avg_dom": self._compute_avg_dom(
                    cr, lead_domain_base, is_admin, target_ids, user_id),
                "avg_sale_price": self._compute_avg_sale_price(
                    cr, order_user_filter),
                "active_listings": self._compute_active_listings(
                    cr),
                "referral_rate": self._compute_referral_rate(
                    cr, lead_domain_base, is_admin, target_ids, user_id),
                "response_time_hours": self._compute_response_time(
                    cr, lead_domain_base, is_admin, target_ids, user_id),
                "activities_per_lead": self._compute_activities_per_lead(
                    cr, lead_domain_base, is_admin, target_ids, user_id),
                "stalled_deal_rate": self._compute_stalled_deal_rate(
                    cr, lead_domain_base, is_admin, target_ids, user_id),
                "quota_attainment": self._compute_quota_attainment(
                    cr, confirmed_revenue, is_admin),
                "source_conversion": self._compute_source_conversion(
                    cr, lead_domain_base, is_admin, target_ids, user_id),
                # ─── NEW: Date-scoped Real Estate KPIs ─────────────
                "transaction_stages": self._compute_transaction_stages(
                    cr, lead_domain_base, is_admin, target_ids, user_id, date_filter, date_params),
                "property_type_breakdown": self._compute_property_type_breakdown(
                    cr, lead_domain_base, is_admin, target_ids, user_id, date_filter, date_params),
                "listing_activity": self._compute_listing_activity(
                    cr, lead_domain_base, is_admin, target_ids, user_id, date_filter, date_params),
                "market_velocity": self._compute_market_velocity(
                    cr, lead_domain_base, is_admin, target_ids, user_id, date_filter, date_params),
                "commission_summary": self._compute_commission_summary(
                    cr, order_user_filter),
            },
            # ─── Charts (replaces Conversion Funnel, Teams) ─────────────
            "pipeline_aging": pipeline_aging,
            "owner_pipeline": owner_pipeline,
            "pipeline_by_source": pipeline_by_source,
            # ─── Qualification & Gate Compliance (sgc_sales_playbook) ───
            "qualification": {
                "enabled": sgc_playbook_installed,
                "gate_stage_configured": gate_stage_configured,
                "gate_pass_rate": gate_pass_rate,
                "gate_pass_rate_n": gate_pass_rate_n,
                "gate_pass_rate_ai": gate_pass_rate_ai,
                "gate_pass_rate_ai_n": gate_pass_rate_ai_n,
                "gate_pass_rate_human": gate_pass_rate_human,
                "gate_pass_rate_human_n": gate_pass_rate_human_n,
                "stalled_deals_count": stalled_deals_count,
                "objection_conversion_rate": objection_conversion_rate,
                "objection_conversion_rate_n": objection_conversion_rate_n,
                "stale_lead_count": stale_lead_count,
            },
            # ─── Kept widgets ──────────────────────────────────────────
            "funnel": funnel_stages,
            "stages": stages,
            "salesperson": salesperson_data[:10] if is_admin and not user_id else salesperson_data,
            "monthly": monthly,
        }

    # ═══════════════════════════════════════════════════════════════
    #  Real Estate KPI computation helpers
    #  All fields resolved dynamically so this module is portable
    #  across tenants with different stage names / pipeline configs.
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _compute_conversion_rate(won, lost, pipeline):
        """Lead-to-close conversion rate.
        Denominator = all non-active leads (won + lost) + active pipeline.
        Returns None when denominator is 0."""
        denom = won + lost + pipeline
        return round(won / denom * 100.0, 1) if denom else None

    @api.model
    def _compute_avg_dom(self, cr, lead_domain_base, is_admin, target_ids, user_id):
        """Average Days on Market = avg(create_date → date_closed) for won leads.
        Uses only stock crm.lead fields — no schema changes required."""
        user_filter, params = self._lead_user_filter(user_id, is_admin, target_ids)
        won_stage_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
        if not won_stage_ids:
            return None
        won_sql = ",".join(map(str, won_stage_ids))
        cr.execute(f"""
            SELECT AVG(EXTRACT(EPOCH FROM (date_closed - create_date))/86400.0) AS avg_dom
            FROM crm_lead
            WHERE active = true
              AND stage_id IN ({won_sql})
              AND date_closed IS NOT NULL
              AND create_date IS NOT NULL
              {user_filter}
        """, params)
        row = cr.fetchone()
        return round(row[0], 1) if row and row[0] else None

    @api.model
    def _compute_avg_sale_price(self, cr, order_user_filter):
        """Average confirmed sale order value."""
        cr.execute("""
            SELECT AVG(amount_total) FROM sale_order
            WHERE state = 'sale'
        """)
        row = cr.fetchone()
        return round(row[0], 2) if row and row[0] else None

    @api.model
    def _compute_active_listings(self, cr):
        """Count of sale.contract records in active listing states.
        Falls back to 0 if the model doesn't exist (tenant without
        sgc_offplan_rental_property_management)."""
        if "sale.contract" not in self.env:
            return 0
        try:
            return self.env["sale.contract"].search_count([
                ("state", "in", ("draft", "signed")),
            ])
        except Exception:
            return 0

    @api.model
    def _compute_referral_rate(self, cr, lead_domain_base, is_admin, target_ids, user_id):
        """% of leads whose UTM source name contains 'referral' (case-insensitive).
        Dynamic: uses UTM source name, no hardcoded source IDs."""
        user_filter, params = self._lead_user_filter(user_id, is_admin, target_ids)
        cr.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE LOWER(COALESCE(s.name,'')) LIKE '%%referral%%') AS referral_cnt,
                COUNT(*) AS total_cnt
            FROM crm_lead l
            LEFT JOIN utm_source s ON l.source_id = s.id
            WHERE l.active = true
              {user_filter}
        """, params)
        row = cr.dictfetchone()
        if not row or not row["total_cnt"]:
            return None
        return round(row["referral_cnt"] / row["total_cnt"] * 100.0, 1)

    @api.model
    def _compute_response_time(self, cr, lead_domain_base, is_admin, target_ids, user_id):
        """Average hours from lead create_date to first mail_activity date.
        Surfaces speed-to-lead — the #1 predictor of conversion in real estate."""
        user_filter, params = self._lead_user_filter(user_id, is_admin, target_ids)
        cr.execute(f"""
            SELECT AVG(EXTRACT(EPOCH FROM (a.create_date - l.create_date))/3600.0) AS avg_hours
            FROM crm_lead l
            JOIN mail_activity a ON a.res_id = l.id AND a.res_model = 'crm.lead'
            WHERE l.active = true
              AND a.create_date IS NOT NULL
              AND l.create_date IS NOT NULL
              {user_filter}
        """, params)
        row = cr.fetchone()
        return round(row[0], 1) if row and row[0] else None

    @api.model
    def _compute_activities_per_lead(self, cr, lead_domain_base, is_admin, target_ids, user_id):
        """Total mail_activities across active leads ÷ active lead count."""
        user_filter, params = self._lead_user_filter(user_id, is_admin, target_ids)
        cr.execute(f"""
            SELECT
                COUNT(a.id) AS activity_cnt,
                COUNT(DISTINCT l.id) AS lead_cnt
            FROM crm_lead l
            LEFT JOIN mail_activity a ON a.res_id = l.id AND a.res_model = 'crm.lead'
            WHERE l.active = true
              {user_filter}
        """, params)
        row = cr.dictfetchone()
        if not row or not row["lead_cnt"]:
            return None
        return round(row["activity_cnt"] / row["lead_cnt"], 1)

    @api.model
    def _compute_stalled_deal_rate(self, cr, lead_domain_base, is_admin, target_ids, user_id):
        """% of active leads with no activity in 14+ days.
        Uses write_date as proxy for last activity."""
        user_filter, params = self._lead_user_filter(user_id, is_admin, target_ids)
        cutoff = fields.Datetime.to_string(datetime.now() - timedelta(days=14))
        cr.execute(f"""
            SELECT
                COUNT(*) FILTER (WHERE write_date <= %s) AS stalled,
                COUNT(*) AS total
            FROM crm_lead
            WHERE active = true
              {user_filter}
        """, [cutoff] + list(params))
        row = cr.dictfetchone()
        if not row or not row["total"]:
            return None
        return round(row["stalled"] / row["total"] * 100.0, 1)

    @api.model
    def _compute_quota_attainment(self, cr, confirmed_revenue, is_admin):
        """Revenue vs. crm.team dashboard_target_revenue.
        Returns None when no target is configured (tenant without quotas)."""
        cr.execute("SELECT COALESCE(SUM(dashboard_target_revenue),0) FROM crm_team")
        target = cr.fetchone()[0] or 0
        if not target:
            return None
        return round(confirmed_revenue / target * 100.0, 1)

    @api.model
    def _compute_source_conversion(self, cr, lead_domain_base, is_admin, target_ids, user_id):
        """Per-source conversion rate: won_leads / total_leads per UTM source.
        Returns list of {source, total, won, rate} sorted by rate desc."""
        user_filter, params = self._lead_user_filter(user_id, is_admin, target_ids)
        won_stage_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
        if not won_stage_ids:
            return []
        won_sql = ",".join(map(str, won_stage_ids))
        cr.execute(f"""
            SELECT source_name, total, won
            FROM (
                SELECT
                    COALESCE(NULLIF(s.name, ''), 'Unassigned') AS source_name,
                    COUNT(l.id) AS total,
                    COUNT(*) FILTER (WHERE l.stage_id IN ({won_sql})) AS won
                FROM crm_lead l
                LEFT JOIN utm_source s ON l.source_id = s.id
                WHERE l.active = true
                  {user_filter}
                GROUP BY source_name
                HAVING COUNT(l.id) >= 3
            ) sub
            ORDER BY won * 100.0 / NULLIF(total,0) DESC
            LIMIT 10
        """, params)
        return [
            {"source": r["source_name"], "total": r["total"], "won": r["won"],
             "rate": round(r["won"] / r["total"] * 100.0, 1) if r["total"] else 0}
            for r in cr.dictfetchall()
        ]

    @staticmethod
    def _lead_user_filter(user_id, is_admin, target_ids, date_filter=None, date_params=None):
        """Return (SQL filter string, params list) for lead user scoping.
        Shared helper so all KPI queries use the same filter logic."""
        if user_id:
            return "AND l.user_id = %s", [user_id]
        elif not is_admin:
            return "AND l.user_id IN %s", [tuple(target_ids)]
        return "", []

    def _date_range_domain(self, date_range):
        """Convert a date_range string ('7d', '30d', '90d', '6m', '12m',
        'today', 'custom_start,end') to an Odoo domain for crm_lead
        create_date filtering. Returns list of domain tuples."""
        from datetime import datetime, timedelta
        if not date_range or date_range in ("", "all"):
            return []
        today = fields.Date.context_today(self)
        if date_range == "today":
            return [("create_date", ">=", fields.Datetime.to_string(datetime.combine(today, datetime.min.time())))]
        if date_range == "7d":
            start = today - timedelta(days=6)
            return [("create_date", ">=", fields.Datetime.to_string(datetime.combine(start, datetime.min.time())))]
        if date_range == "30d":
            start = today - timedelta(days=29)
            return [("create_date", ">=", fields.Datetime.to_string(datetime.combine(start, datetime.min.time())))]
        if date_range == "90d":
            start = today - timedelta(days=89)
            return [("create_date", ">=", fields.Datetime.to_string(datetime.combine(start, datetime.min.time())))]
        if date_range == "6m":
            start = today - timedelta(days=179)
            return [("create_date", ">=", fields.Datetime.to_string(datetime.combine(start, datetime.min.time())))]
        if date_range == "12m":
            start = today - timedelta(days=364)
            return [("create_date", ">=", fields.Datetime.to_string(datetime.combine(start, datetime.min.time())))]
        if date_range.startswith("custom"):
            try:
                parts = date_range.split(",", 1)
                return [("create_date", ">=", parts[0]), ("create_date", "<=", parts[1])]
            except Exception:
                return []
        return []

    # ─── Drill-down: "what records are behind this number?" ─────────────
    # Every KPI card, qualification tile and chart segment on the
    # dashboard is a count or a rate computed above. open_records() maps a
    # click on one of those back to the crm.lead (or sale.order /
    # sgc.lead.objection) records that produced it, as a real window
    # action — so clicking "Won: 12" opens exactly those 12 leads, not an
    # approximation. Domains here intentionally mirror the ones above
    # rather than sharing helper functions with them line-for-line: most
    # already funnel through the shared _scope()/lead_domain_base, and
    # keeping the rest as short, self-contained blocks (each next to a
    # comment naming which KPI it must match) makes it possible to spot a
    # drift between "the number" and "the list" by reading the two blocks
    # side by side, which a deeper shared abstraction would hide.
    _AGING_BUCKETS = {
        # bucket key -> (days_ago_low, days_ago_high); mirrors the SQL CASE
        # in get_dashboard_data's pipeline_aging query exactly.
        "0-7": (0, 7),
        "8-30": (8, 30),
        "31-60": (31, 60),
        "61-90": (61, 90),
        "90p": (91, None),
    }

    def _aging_bucket_domain(self, bucket):
        if bucket not in self._AGING_BUCKETS:
            raise UserError(_("Unknown pipeline-aging bucket: %s", bucket))
        lo, hi = self._AGING_BUCKETS[bucket]
        today = fields.Date.context_today(self)
        domain = []
        if hi is not None:
            start = today - timedelta(days=hi)
            domain.append(("create_date", ">=", fields.Datetime.to_string(datetime.combine(start, datetime.min.time()))))
        end = today - timedelta(days=lo)
        domain.append(("create_date", "<=", fields.Datetime.to_string(datetime.combine(end, datetime.max.time()))))
        return domain

    @staticmethod
    def _month_bounds(month_key):
        """('2026-07', ) -> (datetime str, datetime str) covering that month."""
        year, month = (int(p) for p in month_key.split("-"))
        start = datetime(year, month, 1)
        end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
        return fields.Datetime.to_string(start), fields.Datetime.to_string(end)

    @staticmethod
    def _lead_action(name, domain, extra_context=None):
        return {
            "type": "ir.actions.act_window",
            "name": name,
            "res_model": "crm.lead",
            "view_mode": "list,kanban,form",
            "views": [[False, "list"], [False, "kanban"], [False, "form"]],
            "domain": domain,
            "context": {"create": False, **(extra_context or {})},
            "target": "current",
        }

    @api.model
    def open_records(self, kind, params=None, user_id=None, date_range=None):
        """Return an ir.actions.act_window dict for the records behind a
        dashboard KPI/chart segment.

        `user_id` must be the salesperson-filter value the dashboard was
        showing when the user clicked (the admin dropdown selection) so the
        opened list always matches what was on screen — the frontend passes
        state.selectedUserId on every call.

        date_range, if provided, filters the opened list to the same window
        the dashboard is showing, so click-through always shows the exact
        records behind the displayed number.
        """
        params = params or {}
        is_admin, target_ids, lead_domain_base, date_filter, date_params = self._scope(user_id, date_range)
        sm = self._stage_map()

        # ── Scorecard row 1 ──────────────────────────────────────────
        date_domain = self._date_range_domain(date_range)
        if kind == "kpi_pipeline":
            return self._lead_action(_("In Pipeline"), lead_domain_base + [
                ("active", "=", True), ("probability", ">", 0), ("probability", "<", 100),
            ] + date_domain)
        if kind == "kpi_new_leads_today":
            # Opens the same set the count comes from: active leads currently
            # in the New stage, scoped to the selected user filter.
            new_stage_id = sm["new"]
            domain = [("active", "=", True)]
            if new_stage_id:
                domain.append(("stage_id", "=", new_stage_id))
            if user_id:
                domain.append(("user_id", "=", user_id))
            elif not is_admin:
                domain.append(("user_id", "in", target_ids))
            domain += date_domain
            return self._lead_action(_("New Leads Today"), domain)
        if kind == "kpi_moved_out_of_new":
            new_stage_id = sm["new"]
            today_start = fields.Datetime.to_string(
                datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            )
            domain = [("active", "=", True), ("write_date", ">=", today_start)]
            if new_stage_id:
                domain.append(("stage_id", "!=", new_stage_id))
            if user_id:
                domain.append(("user_id", "=", user_id))
            elif not is_admin:
                domain.append(("user_id", "in", target_ids))
            domain += date_domain
            return self._lead_action(_("Moved Out of New Today"), domain)
        if kind == "kpi_won":
            won_stage_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
            return self._lead_action(_("Won"), lead_domain_base + [("stage_id", "in", won_stage_ids)] + date_domain)
        if kind == "kpi_lost":
            return self._lead_action(_("Lost"), lead_domain_base + [
                "|", ("active", "=", False), ("probability", "=", 0),
            ] + date_domain)

        # ── Scorecard row 2 ──────────────────────────────────────────
        if kind == "kpi_follow_up":
            return self._lead_action(_("Follow Up"), lead_domain_base + [("active", "=", True), ("stage_id", "=", sm["follow_up"] or 0)] + date_domain)
        if kind == "kpi_research_done":
            return self._lead_action(_("Qualified"), lead_domain_base + [("active", "=", True), ("stage_id", "=", sm["research_done"] or 0)] + date_domain)
        if kind == "kpi_outreach_email":
            return self._lead_action(_("Email Outreach"), lead_domain_base + [("active", "=", True), ("stage_id", "=", sm["outreach_email"] or 0)] + date_domain)
        if kind == "kpi_booked":
            return self._lead_action(_("Proposition"), lead_domain_base + [("active", "=", True), ("stage_id", "=", sm["meeting_booked"] or 0)] + date_domain)
        if kind == "kpi_revenue":
            # confirmed_revenue sums ALL confirmed sale.order regardless of
            # salesperson filter — mirrored here, not scoped either.
            return {
                "type": "ir.actions.act_window",
                "name": _("Confirmed Revenue"),
                "res_model": "sale.order",
                "view_mode": "list,form",
                "views": [[False, "list"], [False, "form"]],
                "domain": [("state", "=", "sale")],
                "context": {"create": False},
                "target": "current",
            }

        # ── Real Estate KPI drill-downs ────────────────────────
        if kind == "kpi_conversion_rate":
            return self._lead_action(_("Leads (won / total)"), lead_domain_base + [
                ("active", "=", True),
                "|", ("stage_id", "in", self.env["crm.stage"].search([("is_won", "=", True)]).ids),
                     ("probability", "=", 0),
            ] + date_domain)
        if kind == "kpi_avg_dom":
            won_stage_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
            return self._lead_action(_("Avg Days on Market"), lead_domain_base + [
                ("active", "=", True), ("stage_id", "in", won_stage_ids),
                ("date_closed", "!=", False),
            ] + date_domain)
        if kind == "kpi_avg_sale_price":
            return {
                "type": "ir.actions.act_window",
                "name": _("Confirmed Sale Orders"),
                "res_model": "sale.order",
                "view_mode": "list,form",
                "views": [[False, "list"], [False, "form"]],
                "domain": [("state", "=", "sale")],
                "context": {"create": False},
                "target": "current",
            }
        if kind == "kpi_active_listings":
            if "sale.contract" not in self.env:
                raise UserError(_("sale.contract model not available — install sgc_offplan_rental_property_management."))
            return {
                "type": "ir.actions.act_window",
                "name": _("Active Listings"),
                "res_model": "sale.contract",
                "view_mode": "list,form",
                "views": [[False, "list"], [False, "form"]],
                "domain": [("state", "in", ("draft", "signed"))],
                "context": {"create": False},
                "target": "current",
            }
        if kind == "kpi_commission":
            return {
                "type": "ir.actions.act_window",
                "name": _("Commission Summary"),
                "res_model": "sale.order",
                "view_mode": "list,form",
                "views": [[False, "list"], [False, "form"]],
                "domain": [("state", "=", "sale")],
                "context": {"create": False},
                "target": "current",
            }
        if kind == "kpi_transaction":
            return self._lead_action(_("Transaction Pipeline"), lead_domain_base + [
                ("active", "=", True),
            ] + date_domain)
        if kind == "kpi_property_type":
            if "sale.contract" not in self.env:
                raise UserError(_("sale.contract model not available — install sgc_offplan_rental_property_management."))
            return {
                "type": "ir.actions.act_window",
                "name": _("Property Type Breakdown"),
                "res_model": "sale.contract",
                "view_mode": "list,form",
                "views": [[False, "list"], [False, "form"]],
                "domain": [("state", "in", ("draft", "signed"))],
                "context": {"create": False},
                "target": "current",
            }
        if kind == "kpi_listing_activity":
            return {
                "type": "ir.actions.act_window",
                "name": _("Listing Activity"),
                "res_model": "property.details",
                "view_mode": "list,form",
                "views": [[False, "list"], [False, "form"]],
                "domain": [],
                "context": {"create": False},
                "target": "current",
            }
        if kind == "kpi_market_velocity":
            return {
                "type": "ir.actions.act_window",
                "name": _("Market Velocity"),
                "res_model": "crm.lead",
                "view_mode": "list,graph",
                "views": [[False, "list"], [False, "graph"]],
                "domain": [("active", "=", True)] + date_domain,
                "context": {"create": False},
                "target": "current",
            }

        # ── Qualification & Gate Compliance (sgc_sales_playbook) ───
        if kind == "qual_gate_pass_rate":
            return self._lead_action(_("Gateable Deals (Meeting Booked+)"), lead_domain_base + [
                ("active", "=", True), ("stage_id.sequence", ">=", 7),
            ] + date_domain)
        if kind == "qual_stalled":
            stall_cutoff = fields.Datetime.to_string(datetime.now() - timedelta(weeks=3))
            return self._lead_action(_("Stalled 3+ Weeks"), lead_domain_base + [
                ("active", "=", True),
                ("date_last_stage_update", "!=", False),
                ("date_last_stage_update", "<=", stall_cutoff),
            ] + date_domain)
        if kind == "qual_objection_conversion":
            if "sgc.lead.objection" not in self.env:
                raise UserError(_("Objection tracking isn't installed (sgc_sales_playbook)."))
            if user_id:
                obj_domain = [("lead_id.user_id", "=", user_id)]
            elif not is_admin:
                obj_domain = [("lead_id.user_id", "in", target_ids)]
            else:
                obj_domain = []
            return {
                "type": "ir.actions.act_window",
                "name": _("Objections"),
                "res_model": "sgc.lead.objection",
                "view_mode": "list,form",
                "views": [[False, "list"], [False, "form"]],
                "domain": obj_domain,
                "context": {"create": False},
                "target": "current",
            }
        if kind == "qual_stale":
            stale_cutoff_dt = fields.Datetime.to_string(datetime.now() - timedelta(days=30))
            return self._lead_action(_("Stale, Pending Cleanup"), lead_domain_base + [
                ("active", "=", True),
                ("stage_id", "in", sm["dead"] or [0]),
                ("lost_reason_id", "=", False),
                ("write_date", "<=", stale_cutoff_dt),
            ] + date_domain)

        # ── Charts ─────────────────────────────────────────────
        if kind == "chart_stage":
            # "Pipeline by Stage (Active)" donut — segment identified by
            # stage name, matching the stages[] the chart already renders.
            stage_name = params.get("stage_name")
            return self._lead_action(_("Pipeline: %s", stage_name), lead_domain_base + [
                ("active", "=", True), ("stage_id.name", "=", stage_name),
            ] + date_domain)
        if kind == "chart_funnel":
            # "Conversion Funnel" — all-time (active + archived) per stage,
            # matching funnel_stages' f_domain (no active filter).
            stage_name = params.get("stage_name")
            return self._lead_action(_("Funnel: %s", stage_name), lead_domain_base + [
                ("stage_id.name", "=", stage_name),
            ] + date_domain)
        if kind == "chart_aging":
            bucket = params.get("bucket")
            return self._lead_action(_("Pipeline Age: %s", bucket), lead_domain_base + [
                ("active", "=", True),
            ] + self._aging_bucket_domain(bucket) + date_domain)
        if kind == "chart_owner":
            owner_id = params.get("owner_id")
            owner = self.env["res.users"].browse(owner_id)
            return self._lead_action(_("Pipeline: %s", owner.display_name), [
                ("active", "=", True), ("user_id", "=", owner_id),
            ] + date_domain)
        if kind == "chart_source":
            # Matches pipeline_by_source, which collapses NULL/blank UTM
            # source into a single "Unassigned" bucket by display name.
            source_name = params.get("source_name")
            domain = lead_domain_base + [("active", "=", True)]
            domain += [("source_id", "=", False)] if source_name == "Unassigned" else [("source_id.name", "=", source_name)]
            return self._lead_action(_("Pipeline Source: %s", source_name), domain + date_domain)
        if kind == "chart_monthly":
            month = params.get("month")
            series = params.get("series")
            start, end = self._month_bounds(month)
            if series == "created":
                domain = lead_domain_base + [("create_date", ">=", start), ("create_date", "<", end)]
            elif series == "won":
                won_stage_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
                domain = lead_domain_base + [
                    ("date_closed", ">=", start), ("date_closed", "<", end),
                    ("active", "=", True), ("stage_id", "in", won_stage_ids),
                ]
            elif series == "lost":
                domain = lead_domain_base + [
                    ("date_closed", ">=", start), ("date_closed", "<", end),
                    ("active", "=", False),
                ]
            else:
                raise UserError(_("Unknown Pipeline Movement series: %s", series))
            return self._lead_action(_("%(series)s — %(month)s", series=series.capitalize(), month=month), domain)

        raise UserError(_("Unknown dashboard drill-down: %s", kind))

    @api.model
    def get_salesperson_detail(self, user_id):
        """Return detailed productivity data for a single salesperson."""
        cr = self.env.cr

        won_stage_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
        won_stage_ids_sql = ",".join(map(str, won_stage_ids)) if won_stage_ids else "0"
        cr.execute(f"""
            SELECT
                count(*) as total,
                SUM(CASE WHEN active=true AND stage_id IN ({won_stage_ids_sql}) THEN 1 ELSE 0 END) as won,
                SUM(CASE WHEN active=false OR (active=true AND probability=0) THEN 1 ELSE 0 END) as lost,
                SUM(CASE WHEN create_date >= NOW() - INTERVAL '30 days' THEN 1 ELSE 0 END) as last_30d,
                SUM(CASE WHEN create_date >= NOW() - INTERVAL '7 days' THEN 1 ELSE 0 END) as last_7d,
                SUM(CASE WHEN date_open IS NOT NULL THEN 1 ELSE 0 END) as accepted,
                SUM(CASE WHEN day_open IS NOT NULL THEN day_open ELSE 0 END)::float /
                    NULLIF(SUM(CASE WHEN day_open IS NOT NULL THEN 1 ELSE 0 END), 0) as avg_days_to_close,
                MAX(CASE WHEN active=true AND stage_id IN ({won_stage_ids_sql}) THEN date_closed END) as last_win_date,
                MAX(write_date) as last_activity_date
            FROM crm_lead WHERE user_id = %s
        """, (user_id,))
        row = cr.dictfetchone()

        now = datetime.now()
        last_win = row["last_win_date"]
        last_act = row["last_activity_date"]
        days_since_win = (now - last_win.replace(tzinfo=None)).days if last_win else None
        days_since_act = (now - last_act.replace(tzinfo=None)).days if last_act else None

        # Stage breakdown
        lang = self.env.user.lang or 'en_US'
        cr.execute("""
            SELECT s.name->>%s as stage, count(*) as count
            FROM crm_lead l
            JOIN crm_stage s ON l.stage_id = s.id
            WHERE l.user_id = %s AND l.active = true
            GROUP BY s.name, s.sequence ORDER BY s.sequence
        """, (lang, user_id,))
        user_stages = [{"name": r["stage"], "count": r["count"]} for r in cr.dictfetchall()]

        # Activities
        cr.execute("""
            SELECT
                count(*) as total,
                SUM(CASE WHEN date_done IS NOT NULL THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN date_done IS NULL AND date_deadline < CURRENT_DATE THEN 1 ELSE 0 END) as overdue,
                SUM(CASE WHEN date_done IS NULL AND date_deadline >= CURRENT_DATE THEN 1 ELSE 0 END) as pending
            FROM mail_activity
            WHERE user_id = %s AND res_model = 'crm.lead'
        """, (user_id,))
        act = cr.dictfetchone()

        # Activity types breakdown
        cr.execute("""
            SELECT at.name->>%s as type, count(*) as total,
                SUM(CASE WHEN a.date_done IS NOT NULL THEN 1 ELSE 0 END) as done
            FROM mail_activity a
            JOIN mail_activity_type at ON a.activity_type_id = at.id
            WHERE a.user_id = %s AND a.res_model = 'crm.lead'
            GROUP BY at.name ORDER BY total DESC
        """, (lang, user_id,))
        act_types = [{"type": r["type"], "total": r["total"], "done": r["done"]} for r in cr.dictfetchall()]

        # Recent leads
        cr.execute("""
            SELECT l.name, l.create_date, l.probability, l.active,
                s.name->>%s as stage
            FROM crm_lead l
            LEFT JOIN crm_stage s ON l.stage_id = s.id
            WHERE l.user_id = %s
            ORDER BY l.create_date DESC LIMIT 10
        """, (lang, user_id,))
        recent_leads = [{
            "name": r["name"] or "Unnamed",
            "create_date": r["create_date"].strftime("%Y-%m-%d") if r["create_date"] else "",
            "probability": r["probability"] or 0,
            "active": r["active"],
            "stage": r["stage"] or "Unassigned",
        } for r in cr.dictfetchall()]

        return {
            "leads": {
                "total": row["total"] or 0,
                "won": row["won"] or 0,
                "lost": row["lost"] or 0,
                "last_30d": row["last_30d"] or 0,
                "last_7d": row["last_7d"] or 0,
                "accepted": row["accepted"] or 0,
                "avg_days_to_close": round(row["avg_days_to_close"] or 0, 1),
                "days_since_win": days_since_win,
                "days_since_activity": days_since_act,
                "days_without_booking": days_since_win if days_since_win is not None else days_since_act,
            },
            "stages": user_stages,
            "activities": {
                "total": act["total"] or 0,
                "done": act["done"] or 0,
                "overdue": act["overdue"] or 0,
                "pending": act["pending"] or 0,
            },
            "activity_types": act_types,
            "recent_leads": recent_leads,
        }

    @api.model
    def get_leaderboard_mini(self):
        """Compact leaderboard snippet for the dashboard: top 5 salespeople
        by a computed score, restricted to actual sales team members (a
        linked hr.employee, on a crm.team) with the same admin exclusion as
        sgc_employee_badges' /sgc/leaderboard (Administrator / Settings
        groups don't compete), plus the current user's own rank if they
        aren't already in the top 5. Requires sgc_employee_badges (declared
        as a hard dependency) for the gamification models this dashboard
        otherwise touches.

        The rank/score here is a display-only computation, NOT real Odoo
        karma - it is never written to gamification.badge.user or
        res.users.karma. It rewards two behaviors:
          - meetings_booked: all-time count of calendar.event records the
            rep created against an opportunity.
          - pipeline_value: expected_revenue summed over the rep's *active
            Proposal-stage* leads only - the same gate stage
            sgc_sales_playbook's Qualification & Gate Compliance card
            enforces (crm.lead._get_gate_stage()), so both cards agree on
            what "Proposal" means. Falls back to 0 for everyone if
            sgc_sales_playbook isn't installed or its gate stage is
            misconfigured (fails open, same as the qualification card).
        Provisional weights (50 pts/meeting, 1 pt per AED 1,000 of
        proposal pipeline) - tune if these don't feel right in practice.
        """
        admin_group_ids = [
            g.id for g in (
                self.env.ref("base.group_erp_manager", raise_if_not_found=False),
                self.env.ref("base.group_system", raise_if_not_found=False),
            ) if g
        ]
        sales_team_user_ids = self.env["crm.team.member"].sudo().search([]).mapped("user_id").ids
        domain = [
            ("share", "=", False),
            ("active", "=", True),
            ("employee_ids", "!=", False),
            ("id", "in", sales_team_user_ids),
        ]
        if admin_group_ids:
            domain.append(("group_ids", "not in", admin_group_ids))
        users = self.env["res.users"].sudo().search_read(domain, ["id", "name"])
        user_ids = [u["id"] for u in users]

        meetings_by_user = {}
        if user_ids:
            self.env.cr.execute("""
                SELECT create_uid, COUNT(*) AS meetings
                  FROM calendar_event
                 WHERE opportunity_id IS NOT NULL
                   AND create_uid = ANY(%s)
              GROUP BY create_uid
            """, (user_ids,))
            meetings_by_user = {
                row["create_uid"]: int(row["meetings"] or 0)
                for row in self.env.cr.dictfetchall()
            }

        sgc_playbook_installed = bool(self.env["ir.module.module"].sudo().search_count([
            ("name", "=", "sgc_sales_playbook"), ("state", "=", "installed"),
        ]))
        proposal_pipeline_by_user = {}
        if sgc_playbook_installed and user_ids:
            gate_stage = self.env["crm.lead"]._get_gate_stage()
            if gate_stage:
                self.env.cr.execute("""
                    SELECT user_id, COALESCE(SUM(expected_revenue), 0) AS pipeline_value
                      FROM crm_lead
                     WHERE active = TRUE
                       AND stage_id = %s
                       AND user_id = ANY(%s)
                  GROUP BY user_id
                """, (gate_stage.id, user_ids))
                proposal_pipeline_by_user = {
                    row["user_id"]: float(row["pipeline_value"] or 0)
                    for row in self.env.cr.dictfetchall()
                }

        for u in users:
            u["meetings_booked"] = meetings_by_user.get(u["id"], 0)
            u["pipeline_value"] = proposal_pipeline_by_user.get(u["id"], 0.0)
            u["score"] = u["meetings_booked"] * 50 + u["pipeline_value"] / 1000.0

        users.sort(key=lambda u: u["score"], reverse=True)
        for i, u in enumerate(users):
            u["rank"] = i + 1

        top = users[:5]
        me = next((u for u in users if u["id"] == self.env.uid), None)
        me_in_top = bool(me) and me["rank"] <= 5

        def _entry(u):
            return {
                "id": u["id"],
                "name": u["name"],
                "rank": u["rank"],
                "score": round(u["score"]),
                "meetings_booked": u["meetings_booked"],
                "pipeline_value": u["pipeline_value"],
            }

        return {
            "top": [_entry(u) for u in top],
            "me": _entry(me) if me and not me_in_top else None,
        }

    # ═══════════════════════════════════════════════════════════════
    #  NEW: Date-scoped Real Estate KPI Helpers
    # ═══════════════════════════════════════════════════════════════

    @api.model
    def _user_filter_sql(self, user_id, is_admin, target_ids):
        """Return (SQL filter string, params) for user scoping. Shared so all
        KPI queries use the same filter logic."""
        if user_id:
            return "AND l.user_id = %s", [user_id]
        elif not is_admin:
            return "AND l.user_id IN %s", [tuple(target_ids)]
        return "", []

    @api.model
    def _compute_transaction_stages(self, cr, lead_domain_base, is_admin, target_ids, user_id, date_filter, date_params):
        """Transaction pipeline stage tracker — count of active leads per
        pipeline stage. This is the "deal tracker" real estate managers
        need to see: how many leads are at each step of the transaction.
        Returns list sorted by stage sequence with counts and % of open."""
        won_stage_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
        user_filter, params = self._user_filter_sql(user_id, is_admin, target_ids)
        if date_filter:
            user_filter = user_filter + date_filter
            params = params + (date_params or [])
        cr.execute(f"""
            SELECT
                s.id, s.name->>%s as stage_name, s.sequence,
                COUNT(l.id) FILTER (WHERE l.active = true) as count
            FROM crm_stage s
            LEFT JOIN crm_lead l ON l.stage_id = s.id {user_filter}
            GROUP BY s.id, s.name, s.sequence
            ORDER BY s.sequence
        """, (self.env.user.lang or 'en_US',) + tuple(params))
        rows = cr.dictfetchall()
        total_open = sum(r["count"] for r in rows)
        result = []
        for r in rows:
            pct = round((r["count"] / total_open * 100.0), 1) if total_open else 0
            result.append({
                "name": r["stage_name"],
                "count": r["count"],
                "pct": pct,
                "seq": r["sequence"],
            })
        result.sort(key=lambda x: x["seq"])
        return result

    @api.model
    def _compute_property_type_breakdown(self, cr, lead_domain_base, is_admin, target_ids, user_id, date_filter, date_params):
        """Property type breakdown for active listings (requires
        sgc_offplan_rental_property_management). Counts sale.contract by
        property_type (or falls back to contract type)."""
        if "sale.contract" not in self.env:
            return []
        try:
            Contract = self.env["sale.contract"]
        except Exception:
            return []
        params = []
        date_clause = ""
        if date_filter:
            # date_filter is built against crm_lead.create_date; re-point at contract.
            date_clause = " " + date_filter.replace("l.create_date", "c.create_date")
            params = list(date_params or [])
        cr.execute(f"""
            SELECT
                COALESCE(NULLIF(p.property_type, ''), 'Other') AS property_type,
                COUNT(c.id) AS count
            FROM sale_contract c
            JOIN property_details p ON c.property_id = p.id
            WHERE c.state IN ('draft', 'signed')
              {date_clause}
            GROUP BY p.property_type
            ORDER BY count DESC
        """, tuple(params))
        return [
            {"name": r["property_type"], "count": r["count"]}
            for r in cr.dictfetchall()
        ]

    @api.model
    def _compute_listing_activity(self, cr, lead_domain_base, is_admin, target_ids, user_id, date_filter, date_params):
        """Listing activity summary — new/published/withdrawn listings over the
        selected date range. Real estate managers need to see listing velocity,
        not just the static "active listings" count. Measured over
        property.details (the listings themselves)."""
        if "property.details" not in self.env:
            return {"new": 0, "published": 0, "withdrawn": 0}

        date_clause = ""
        params = []
        if date_filter:
            # date_filter is built against crm_lead.create_date; re-point at listings.
            date_clause = " " + date_filter.replace("l.create_date", "p.create_date")
            params = list(date_params or [])

        result = {}
        cr.execute(f"""
            SELECT COUNT(*) FROM property_details p
            WHERE 1 = 1 {date_clause}
        """, tuple(params))
        result["new"] = cr.fetchone()[0] or 0

        cr.execute("SELECT COUNT(*) FROM property_details WHERE is_published_website = true")
        result["published"] = cr.fetchone()[0] or 0

        cr.execute("SELECT COUNT(*) FROM property_details WHERE active = false")
        result["withdrawn"] = cr.fetchone()[0] or 0
        return result

    @api.model
    def _compute_market_velocity(self, cr, lead_domain_base, is_admin, target_ids, user_id, date_filter, date_params):
        """Market velocity — ratio of closed to opened opportunities in the
        selected window. Shows how fast the market is moving and whether
        inventory (leads) is building up faster than it closes."""
        user_filter, params = self._user_filter_sql(user_id, is_admin, target_ids)
        if date_filter:
            user_filter = user_filter + date_filter
            params = params + (date_params or [])
        won_stage_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
        won_sql = ",".join(map(str, won_stage_ids)) if won_stage_ids else "0"
        cr.execute(f"""
            SELECT
                COUNT(l.id) FILTER (WHERE l.active = true) as opened,
                SUM(CASE WHEN l.active = true AND l.stage_id IN ({won_sql}) THEN 1 ELSE 0 END) as closed
            FROM crm_lead l WHERE 1 = 1 {user_filter}
        """, tuple(params))
        row = cr.fetchone()
        opened = row[0] or 0 if row else 0
        closed = row[1] or 0 if row else 0
        velocity = round(closed / opened * 100.0, 1) if opened else None
        return {
            "opened": opened,
            "closed": closed,
            "velocity_pct": velocity,
            "trend": "healthy" if velocity and velocity >= 80 else ("warning" if velocity and velocity >= 50 else "alert"),
        }

    @api.model
    def _compute_commission_summary(self, cr, order_user_filter):
        """Commission summary — expected vs earned commission by salesperson.
        Assumes a commission_rate on sale.order or a team-level commission.
        Returns top sellers with expected/earned commission."""
        if "sale.order" not in self.env:
            return {"expected": 0, "earned": 0, "top_sellers": []}
        try:
            Order = self.env["sale.order"]
        except Exception:
            return {"expected": 0, "earned": 0, "top_sellers": []}
        # Commission rate fallback: try order commission field, else team config
        commission_rate = 0.0
        if Order._fields.get("commission_rate"):
            cr.execute("SELECT COALESCE(AVG(commission_rate), 0) FROM sale_order")
            commission_rate = cr.fetchone()[0] or 0.0
        # If no commission_rate field, try crm.team target revenue
        cr.execute("""
            SELECT COALESCE(SUM(amount_total), 0)
            FROM sale_order so WHERE so.state = 'sale' {order_filter}
        """.format(order_filter=order_user_filter if isinstance(order_user_filter, str) else ""))
        earned_revenue = cr.fetchone()[0] or 0
        cr.execute("""
            SELECT COALESCE(SUM(amount_total), 0)
            FROM sale_order so WHERE so.state IN ('draft', 'sent') {order_filter}
        """.format(order_filter=order_user_filter if isinstance(order_user_filter, str) else ""))
        expected_revenue = cr.fetchone()[0] or 0

        top_sellers = []
        cr.execute("""
            SELECT u.id as user_id, COALESCE(p.name, u.login) as name,
                   COALESCE(SUM(CASE WHEN so.state = 'sale' THEN so.amount_total ELSE 0 END), 0) as earned,
                   COALESCE(SUM(CASE WHEN so.state IN ('draft', 'sent') THEN so.amount_total ELSE 0 END), 0) as expected
            FROM sale_order so
            JOIN res_users u ON so.user_id = u.id
            LEFT JOIN res_partner p ON u.partner_id = p.id
            WHERE so.user_id > 2
            GROUP BY u.id, p.name, u.login
            ORDER BY earned DESC
            LIMIT 5
        """)
        for r in cr.dictfetchall():
            top_sellers.append({
                "id": r["user_id"],
                "name": r["name"],
                "earned": round(r["earned"] or 0, 2),
                "expected": round(r["expected"] or 0, 2),
                "earned_commission": round((r["earned"] or 0) * commission_rate / 100.0, 2),
                "expected_commission": round((r["expected"] or 0) * commission_rate / 100.0, 2),
            })
        return {
            "expected": round(expected_revenue, 2),
            "earned": round(earned_revenue, 2),
            "commission_rate": round(commission_rate, 2),
            "top_sellers": top_sellers,
        }

    @api.model
    def get_property_overview(self, user_id=None, date_range=None):
        """Developer + brokerage block: per-project inventory, collections and
        broker / RM rankings. Reuses property.details.get_development_kpis and
        get_sales_rankings (the Executive Dashboard's own numbers) so the two
        dashboards can never disagree. {} when the property module is absent."""
        if "property.details" not in self.env:
            return {}
        from datetime import timedelta
        today = fields.Date.context_today(self)
        days = {"today": 0, "7d": 6, "30d": 29, "90d": 89, "6m": 179, "12m": 364}
        d_from = d_to = False
        if date_range in days:
            d_from = today - timedelta(days=days[date_range])
        elif date_range and "," in date_range:
            d_from, d_to = date_range.replace("custom", "").strip("_").split(",", 1)
        flt = {"date_from": d_from, "date_to": d_to, "salesperson_id": user_id or 0}
        try:
            Prop = self.env["property.details"]
            k = Prop.get_development_kpis(flt)
            ranks = Prop.get_sales_rankings(flt, limit=10)
        except Exception:
            return {}
        names = {p.code: p.name for p in self.env["property.project"].sudo().search([])}
        projects = [
            {"name": names.get(code) or code or "—", "units": v["units"], "sold": v["sold"],
             "available": max(v["units"] - v["sold"], 0), "sales_value": v["sales_value"],
             "collected": v["collected"]}
            for code, v in (k.get("per_project") or {}).items() if v["units"]
        ]
        projects.sort(key=lambda r: -r["units"])
        keys = ("total_units", "sold_units", "available_units", "sell_through_pct", "sales_value",
                "avg_psf_sold", "collected", "balance_due", "collection_pct")
        return {
            "kpi": {x: k.get(x) for x in keys},
            "projects": projects,
            "brokers": ranks["brokers"],
            "rms": ranks["salespeople"],
        }

    @api.model
    def get_ticker(self):
        """Headlines for the screen-mode news ticker: [{kind, text}], kind in
        win | alert | info. Built from live data; no client names (it is shown
        on a shared screen). An optional free-text banner can be set in
        ir.config_parameter ``sgc_crm_dashboard.ticker_message``."""
        cr = self.env.cr
        items = []
        msg = self.env["ir.config_parameter"].sudo().get_param("sgc_crm_dashboard.ticker_message")
        if msg:
            items.append({"kind": "info", "text": msg})

        won_ids = self.env["crm.stage"].search([("is_won", "=", True)]).ids
        if won_ids:
            cr.execute("""
                SELECT COALESCE(p.name, u.login), COUNT(*)
                FROM crm_lead l JOIN res_users u ON u.id = l.user_id
                LEFT JOIN res_partner p ON p.id = u.partner_id
                WHERE l.stage_id IN %s AND l.date_closed >= CURRENT_DATE
                GROUP BY 1 ORDER BY 2 DESC LIMIT 3
            """, (tuple(won_ids),))
            for name, n in cr.fetchall():
                items.append({"kind": "win", "text": f"{name} closed {n} deal{'s' if n > 1 else ''} today"})

        cr.execute("SELECT COUNT(*) FROM crm_lead WHERE active AND create_date >= CURRENT_DATE")
        n = cr.fetchone()[0]
        if n:
            items.append({"kind": "info", "text": f"{n} new lead{'s' if n > 1 else ''} received today"})

        cr.execute("""
            SELECT COUNT(*) FROM mail_activity
            WHERE res_model = 'crm.lead' AND date_deadline < CURRENT_DATE
        """)
        n = cr.fetchone()[0]
        if n:
            items.append({"kind": "alert", "text": f"{n} overdue follow-up{'s' if n > 1 else ''} need attention"})

        if "property.vendor" in self.env:
            try:
                vendors = self.env["property.vendor"].sudo().search(
                    [("state", "!=", "cancelled")], limit=5)
                for v in vendors:
                    who = (v.salesperson_id or v.create_uid).name
                    unit = v.property_id.name or v.name
                    items.append({"kind": "win", "text": f"New booking: {unit} · {who}"})
                ranks = self.env["property.details"].get_sales_rankings({}, limit=1)
                for label, rows in (("Top broker", ranks["brokers"]), ("Top RM", ranks["salespeople"])):
                    if rows:
                        items.append({"kind": "info", "text": f"{label}: {rows[0]['name']} · AED {self.env['crm.dashboard']._abbrev(rows[0]['value'])}"})
            except Exception:
                pass
        return items

    @staticmethod
    def _abbrev(n):
        for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
            if abs(n) >= div:
                return f"{n / div:.1f}".rstrip("0").rstrip(".") + suf
        return str(round(n))
