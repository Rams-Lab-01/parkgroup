/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Component, onMounted, onWillUnmount, useRef, useState, useEffect } from "@odoo/owl";
import { loadJS } from "@web/core/assets";

export class CrmDashboard extends Component {
    static template = "sgc_crm_dashboard.Dashboard";
    static props = { ...standardActionServiceProps };
    // Positional keys matching the fixed bucket order dashboard.py's
    // pipeline_aging always returns them in (0-7d, 8-30d, 31-60d, 61-90d,
    // 90d+), so the label at index i maps to backend bucket key i here.
    static AGING_BUCKET_KEYS = ["0-7", "8-30", "31-60", "61-90", "90p"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.action = useService("action");
        this.state = useState({
            kpi: {},
            funnel: [],
            stages: [],
            salesperson: [],
            monthly: [],
            pipeline_aging: [],
            owner_pipeline: [],
            pipeline_by_source: [],
            qualification: {},
            loading: true,
            selectedSalesperson: null,
            salespersonDetail: null,
            detailLoading: false,
            isAdmin: false,
            allUsers: [],
            selectedUserId: null,
            currentUserId: null,
            selectedDateRange: "30d",
            leaderboard: { top: [], me: null },
            tv: false,
            ticker: [],
            property: { kpi: {}, projects: [], brokers: [], rms: [] },
        });
        this.chartRefs = {
            projectChart: useRef("projectChart"),
            projectSalesChart: useRef("projectSalesChart"),
            monthlyChart: useRef("monthlyChart"),
            funnelChart: useRef("funnelChart"),
            agingChart: useRef("agingChart"),
            ownerChart: useRef("ownerChart"),
            sourceChart: useRef("sourceChart"),
            sourceConversionChart: useRef("sourceConversionChart"),
        };
        this.root = useRef("root");
        this.charts = {};
        this._chartsReady = false;
        this._timers = [];

        onWillUnmount(() => {
            this.stopTv();
            this.destroyCharts();
        });

        onMounted(async () => {
            await this.loadDashboard();
            if (this.constructor.autoTv) {
                await this.toggleTv();
            }
        });
    }

    async loadDashboard(userId, dateRange = this.state.selectedDateRange, silent = false) {
        this.destroyCharts();
        if (!silent) {
            this.state.loading = true;
        }
        try {
            const params = userId ? [userId] : [];
            const data = await this.orm.call("crm.dashboard", "get_dashboard_data", params, { date_range: dateRange });
            this.state.kpi = data.kpi;
            this.state.funnel = data.funnel;
            this.state.stages = data.stages;
            this.state.salesperson = data.salesperson;
            this.state.monthly = data.monthly;
            this.state.pipeline_aging = data.pipeline_aging || [];
            this.state.owner_pipeline = data.owner_pipeline || [];
            this.state.pipeline_by_source = data.pipeline_by_source || [];
            this.state.qualification = data.qualification || {};
            this.state.isAdmin = data.is_admin;
            this.state.allUsers = data.all_users || [];
            this.state.selectedUserId = data.selected_user_id || null;
            this.state.currentUserId = data.current_user_id;
            this.state.selectedSalesperson = null;
            this.state.salespersonDetail = null;
        } catch (e) {
            this.notification.add("Failed to load dashboard data", { type: "danger" });
        } finally {
            this.state.loading = false;
        }

        // Non-fatal: the leaderboard mini widget shouldn't break the rest
        // of the dashboard if sgc_employee_badges data isn't available yet.
        try {
            this.state.leaderboard = await this.orm.call("crm.dashboard", "get_leaderboard_mini", []);
        } catch (e) {
            this.state.leaderboard = { top: [], me: null };
        }

        // Non-fatal: property/developer block needs the property module.
        try {
            const p = await this.orm.call("crm.dashboard", "get_property_overview", [this.state.selectedUserId], { date_range: dateRange });
            this.state.property = { kpi: {}, projects: [], brokers: [], rms: [], ...p };
        } catch (e) {
            this.state.property = { kpi: {}, projects: [], brokers: [], rms: [] };
        }

        try {
            this.state.ticker = await this.orm.call("crm.dashboard", "get_ticker", []);
        } catch (e) {
            this.state.ticker = [];
        }

        // Wait for OWL to re-render with data, then render charts
        await new Promise((resolve) => setTimeout(resolve, 50));
        await this._ensureChartJs();
        this.renderCharts();
        this.animateCounts();
    }

    /** Screen mode: fullscreen, auto-refresh, slow auto-scroll, ticker. */
    async toggleTv() {
        if (this.state.tv) {
            this.stopTv();
            if (document.fullscreenElement) {
                document.exitFullscreen().catch(() => {});
            }
            return;
        }
        this.state.tv = true;
        try {
            await this.root.el.requestFullscreen();
        } catch (e) { /* kiosk browsers may refuse; screen mode still works */ }
        this._timers.push(setInterval(() => this.loadDashboard(this.state.selectedUserId, this.state.selectedDateRange, true), 60000));
        let dir = 1, pausedUntil = 0;
        const pause = () => { pausedUntil = Date.now() + 15000; };
        this.root.el.addEventListener("wheel", pause);
        this.root.el.addEventListener("touchstart", pause);
        this._timers.push(setInterval(() => {
            const el = this.root.el;
            if (!el || Date.now() < pausedUntil) return;
            el.scrollTop += dir;
            if (el.scrollTop + el.clientHeight >= el.scrollHeight - 1 || el.scrollTop <= 0) {
                dir = -dir;
                pausedUntil = Date.now() + 5000;
            }
        }, 40));
        this._onFsChange = () => { if (!document.fullscreenElement && this.state.tv) this.stopTv(); };
        document.addEventListener("fullscreenchange", this._onFsChange);
    }

    stopTv() {
        this.state.tv = false;
        this._timers.forEach(clearInterval);
        this._timers = [];
        if (this._onFsChange) {
            document.removeEventListener("fullscreenchange", this._onFsChange);
        }
    }

    /** Ticker scroll time scales with text length so speed stays constant. */
    get tickerSeconds() {
        const chars = this.state.ticker.reduce((n, t) => n + t.text.length + 8, 0);
        return Math.max(30, Math.round(chars * 0.25));
    }

    /** Count KPI numbers up from zero ("1,234", "12.5%", "3.2M" keep their affixes). */
    animateCounts() {
        this.root.el?.querySelectorAll(".o_kpi_value").forEach((el) => {
            const m = /^([^\d-]*)(-?[\d,]*\.?\d+)(.*)$/.exec(el.textContent.trim());
            if (!m) return;
            const target = parseFloat(m[2].replace(/,/g, ""));
            const decimals = (m[2].split(".")[1] || "").length;
            const start = performance.now();
            const tick = (now) => {
                const t = Math.min((now - start) / 900, 1);
                const v = target * (1 - Math.pow(1 - t, 3));
                el.textContent = m[1] + v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + m[3];
                if (t < 1) requestAnimationFrame(tick);
            };
            requestAnimationFrame(tick);
        });
    }

    async _ensureChartJs() {
        if (typeof Chart === "undefined") {
            await loadJS("/web/static/lib/Chart/Chart.js");
        }
        // Dashboard is dark: Chart.js defaults (dark text, light grid) are unreadable on it.
        Chart.defaults.color = "#A7B4C6";
        Chart.defaults.borderColor = "rgba(255,255,255,0.08)";
    }

    /** KPI scorecards: one flat list per row so every card renders identically. */
    get salesCards() {
        const k = this.state.kpi;
        const pct = (v) => (v === null || v === undefined ? "N/A" : v + "%");
        return [
            { label: "Open Pipeline", value: this.formatNumber(k.pipeline), icon: "fa-line-chart", color: "#C7A23A", kind: "kpi_pipeline" },
            { label: "Pipeline Value", value: this.formatAbbrev(k.revenue_proposal), sub: "AED · open quotations", icon: "fa-money", color: "#4DA3FF", kind: "kpi_revenue" },
            { label: "Deals Won", value: this.formatNumber(k.won), icon: "fa-trophy", color: "#F4B740", kind: "kpi_won" },
            { label: "Revenue Closed", value: this.formatAbbrev(k.revenue_converted), sub: "AED · confirmed sales", icon: "fa-check-circle", color: "#1EC198", kind: "kpi_revenue" },
            { label: "Win Rate", value: pct(k.conversion_rate), sub: "won / all leads", icon: "fa-bullseye", color: "#7D7EAF", kind: "kpi_won" },
            { label: "Avg Days to Close", value: k.avg_dom != null ? k.avg_dom + "d" : "N/A", sub: "lead created → won", icon: "fa-clock-o", color: "#BD85BA" },
        ];
    }

    get opsCards() {
        const k = this.state.kpi;
        const pct = (v) => (v === null || v === undefined ? "N/A" : v + "%");
        return [
            { label: "Speed to Lead", value: k.response_time_hours != null ? k.response_time_hours + "h" : "N/A", sub: "created → first activity", icon: "fa-bolt", color: "#F4B740" },
            { label: "Activities / Lead", value: k.activities_per_lead != null ? k.activities_per_lead : "N/A", sub: "calls, visits, follow-ups", icon: "fa-tasks", color: "#4DA3FF" },
            { label: "Stalled Rate", value: pct(k.stalled_deal_rate), sub: "no activity 14+ days", icon: "fa-pause-circle", color: "#FF5A5F" },
            { label: "Avg Deal Size", value: this.formatAbbrev(k.avg_sale_price), sub: "AED · confirmed orders", icon: "fa-tag", color: "#C7A23A" },
            { label: "Quota Attainment", value: pct(k.quota_attainment), sub: "revenue vs team target", icon: "fa-flag-checkered", color: "#1EC198" },
            { label: "Collection Rate", value: pct(this.state.property.kpi.collection_pct != null ? Math.round(this.state.property.kpi.collection_pct * 10) / 10 : null), sub: "collected ÷ sales value", icon: "fa-credit-card", color: "#7D7EAF" },
        ];
    }

    /** Developer scorecard from the property module. */
    get propertyCards() {
        const k = this.state.property.kpi;
        const n = (v) => this.formatNumber(v);
        const ok = k.total_units != null;
        return [
            { label: "Total Units", value: ok ? n(k.total_units) : "N/A", sub: "inventory", icon: "fa-building", color: "#4DA3FF" },
            { label: "Units Sold", value: ok ? n(k.sold_units) : "N/A", sub: ok ? `${n(k.available_units)} available` : "", icon: "fa-key", color: "#1EC198" },
            { label: "Sell-through", value: ok ? Math.round(k.sell_through_pct * 10) / 10 + "%" : "N/A", sub: "sold ÷ total units", icon: "fa-tachometer", color: "#F4B740" },
            { label: "Sales Value", value: ok ? this.formatAbbrev(k.sales_value) : "N/A", sub: "AED · sold contracts", icon: "fa-money", color: "#C7A23A" },
            { label: "Collected", value: ok ? this.formatAbbrev(k.collected) : "N/A", sub: ok ? `AED · ${this.formatAbbrev(k.balance_due)} due` : "", icon: "fa-credit-card", color: "#1EC198" },
            { label: "Avg Price / sqft", value: ok ? this.formatNumber(Math.round(k.avg_psf_sold)) : "N/A", sub: "AED · sold units", icon: "fa-area-chart", color: "#BD85BA" },
        ];
    }

    /** Playbook qualification tiles (only shown when sgc_sales_playbook is installed). */
    get qualTiles() {
        const q = this.state.qualification;
        const pct = (v) => (v === null || v === undefined ? "N/A" : v + "%");
        const num = (v) => (v === null || v === undefined ? "N/A" : this.formatNumber(v));
        return [
            { label: "Gate Pass Rate", value: pct(q.gate_pass_rate), sub: `n=${this.formatNumber(q.gate_pass_rate_n)}`, kind: "qual_gate_pass_rate" },
            { label: "Stalled 3+ Weeks", value: num(q.stalled_deals_count), kind: "qual_stalled" },
            { label: "Objection → Meeting", value: pct(q.objection_conversion_rate), sub: `n=${this.formatNumber(q.objection_conversion_rate_n)}`, kind: "qual_objection_conversion" },
            { label: "Stale, Pending Cleanup", value: num(q.stale_lead_count), kind: "qual_stale" },
        ];
    }

    get detailCards() {
        const l = this.state.salespersonDetail.leads;
        const a = this.state.salespersonDetail.activities;
        const n = (v) => this.formatNumber(v);
        return [
            { label: "Total Leads", value: n(l.total) }, { label: "Won", value: n(l.won) },
            { label: "Lost", value: n(l.lost) }, { label: "Avg Days to Close", value: l.avg_days_to_close + "d" },
            { label: "Last 7 Days", value: n(l.last_7d) }, { label: "Last 30 Days", value: n(l.last_30d) },
            { label: "Activities Done", value: n(a.done) }, { label: "Overdue", value: n(a.overdue) },
        ];
    }

    async onFilterChange(ev) {
        const val = ev.target.value;
        const userId = val ? parseInt(val) : null;
        await this.loadDashboard(userId, this.state.selectedDateRange);
    }

    async onDateRangeChange(ev) {
        const val = ev.target.value;
        this.state.selectedDateRange = val;
        // Reset custom date inputs if not custom
        if (val !== 'custom') {
            // Clear custom inputs
            try {
                document.getElementById('date_range_from').value = '';
                document.getElementById('date_range_to').value = '';
            } catch(e) {}
        }
        await this.loadDashboard(this.state.selectedUserId, val);
    }

    async onCustomDateRangeChange(type) {
        const input = document.getElementById(`date_range_${type}`);
        if (input && input.value) {
            // Update the state but don't reload yet
            if (type === 'from') {
                this.state.customDateFrom = input.value;
            } else {
                this.state.customDateTo = input.value;
            }
            // If both are set, apply the range
            if (this.state.customDateFrom && this.state.customDateTo) {
                const customRange = `${this.state.customDateFrom},${this.state.customDateTo}`;
                this.state.selectedDateRange = customRange;
                await this.loadDashboard(this.state.selectedUserId, customRange);
            }
        }
    }

    async onCustomDateRangeApply() {
        if (this.state.customDateFrom && this.state.customDateTo) {
            const customRange = `${this.state.customDateFrom},${this.state.customDateTo}`;
            this.state.selectedDateRange = customRange;
            await this.loadDashboard(this.state.selectedUserId, customRange);
        }
    }

    async selectSalesperson(ev) {
        const userId = parseInt(ev.currentTarget.dataset.userId);
        if (!userId) return;
        this.state.selectedSalesperson = userId;
        this.state.detailLoading = true;
        this.state.salespersonDetail = null;
        try {
            const detail = await this.orm.call("crm.dashboard", "get_salesperson_detail", [userId]);
            this.state.salespersonDetail = detail;
        } catch (e) {
            this.notification.add("Failed to load salesperson detail", { type: "danger" });
        } finally {
            this.state.detailLoading = false;
        }
    }

    closeDetail() {
        this.state.selectedSalesperson = null;
        this.state.salespersonDetail = null;
    }

    /**
     * Open the crm.lead (or sale.order / sgc.lead.objection) records behind
     * a KPI card, qualification tile, or chart segment. `kind`/`params`
     * are forwarded to crm.dashboard.open_records, which builds the exact
     * domain the displayed number came from — see the comment on that
     * method for why the domains live server-side rather than being
     * rebuilt here from state.
     */
    async openRecords(kind, params) {
        try {
            const action = await this.orm.call(
                "crm.dashboard", "open_records", [kind, params || {}, this.state.selectedUserId, this.state.selectedDateRange]
            );
            await this.action.doAction(action);
        } catch (e) {
            this.notification.add(
                e?.data?.message || "Couldn't open the records behind this number",
                { type: "danger" }
            );
        }
    }

    /** Space/Enter on a keyboard-focused clickable card/tile triggers the same click. */
    onClickableKeydown(ev, kind, params) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.openRecords(kind, params);
        }
    }

    /** Leaderboard mini card -> full SGC Leaderboard website page. */
    openLeaderboard() {
        this.action.doAction({ type: "ir.actions.act_url", url: "/sgc/leaderboard", target: "self" });
    }

    onLeaderboardKeydown(ev) {
        if (ev.key === "Enter" || ev.key === " ") {
            ev.preventDefault();
            this.openLeaderboard();
        }
    }

    destroyCharts() {
        Object.values(this.charts).forEach(c => c?.destroy());
        this.charts = {};
    }

    /** Chart.js v4 onHover: swap the cursor to a pointer over a clickable segment. */
    _chartCursorHover(evt, elements) {
        if (evt.native?.target) {
            evt.native.target.style.cursor = elements.length ? "pointer" : "default";
        }
    }

    renderCharts() {
        this.renderProjectCharts();
        this.renderMonthlyChart();
        this.renderFunnelChart();
        this.renderAgingChart();
        this.renderOwnerChart();
        this.renderSourceChart();
        this.renderSourceConversionChart();
    }

    // Developer view: inventory and sales/collections per project.
    renderProjectCharts() {
        const rows = this.state.property.projects;
        if (!rows.length) return;
        const labels = rows.map(r => r.name);
        const stacked = { x: { stacked: true, grid: { display: false } }, y: { stacked: true, beginAtZero: true } };
        const make = (key, ref, datasets, scales, fmt) => {
            const canvas = this.chartRefs[ref]?.el;
            if (!canvas) return;
            if (this.charts[key]) this.charts[key].destroy();
            this.charts[key] = new Chart(canvas, {
                type: "bar",
                data: { labels, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales,
                    plugins: {
                        legend: { labels: { usePointStyle: true, padding: 14 } },
                        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmt(c.raw)}` } },
                    },
                },
            });
        };
        make("project", "projectChart", [
            { label: "Sold", data: rows.map(r => r.sold), backgroundColor: "#1EC198", borderRadius: 4 },
            { label: "Available", data: rows.map(r => r.available), backgroundColor: "#4DA3FF", borderRadius: 4 },
        ], stacked, (v) => this.formatNumber(v) + " units");
        make("projectSales", "projectSalesChart", [
            { label: "Sales value", data: rows.map(r => r.sales_value), backgroundColor: "#C7A23A", borderRadius: 4 },
            { label: "Collected", data: rows.map(r => r.collected), backgroundColor: "#1EC198", borderRadius: 4 },
        ], {
            x: { grid: { display: false } },
            y: { beginAtZero: true, ticks: { callback: (v) => this.formatAbbrev(v) } },
        }, (v) => "AED " + this.formatAbbrev(v));
    }

    renderMonthlyChart() {
        const canvas = this.chartRefs.monthlyChart?.el;
        if (!canvas || !this.state.monthly.length) return;
        if (this.charts.monthly) this.charts.monthly.destroy();
        const labels = this.state.monthly.map(m => m.month);
        this.charts.monthly = new Chart(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [
                    { label: "Created", data: this.state.monthly.map(m => m.created), backgroundColor: "#7D7EAF", borderRadius: 4 },
                    { label: "Won",     data: this.state.monthly.map(m => m.won),     backgroundColor: "#1EC198", borderRadius: 4 },
                    { label: "Lost",    data: this.state.monthly.map(m => m.lost),    backgroundColor: "#FF5A5F", borderRadius: 4 },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true, grid: {} },
                    x: { grid: { display: false } },
                },
                plugins: { legend: { labels: { usePointStyle: true, padding: 16 } } },
                onHover: (evt, elements) => this._chartCursorHover(evt, elements),
                onClick: (evt, elements) => {
                    if (!elements.length) return;
                    const { datasetIndex, index } = elements[0];
                    const series = ["created", "won", "lost"][datasetIndex];
                    const month = this.state.monthly[index];
                    if (series && month) this.openRecords("chart_monthly", { month: month.month, series });
                },
            },
        });
    }

    // Pipeline Aging — bar chart of how many active leads sit in each
    // age bucket. Surfaces "rotting pipeline" before stage breakdowns.
    renderAgingChart() {
        const canvas = this.chartRefs.agingChart?.el;
        if (!canvas || !this.state.pipeline_aging.length) return;
        if (this.charts.aging) this.charts.aging.destroy();
        const labels = this.state.pipeline_aging.map(b => b.bucket);
        const counts = this.state.pipeline_aging.map(b => b.count);
        const colors = counts.map((v, i) => {
            // Red for stale (>60d), amber for warm (8-30d), green for fresh
            if (i >= 3) return "#FF5A5F";
            if (i === 2) return "#FFA48E";
            if (i === 1) return "#FFCA71";
            return "#1EC198";
        });
        const total = counts.reduce((a, b) => a + b, 0) || 1;
        this.charts.aging = new Chart(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Active Leads",
                    data: counts,
                    backgroundColor: colors,
                    borderRadius: 6,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: { beginAtZero: true, grid: {}, ticks: { callback: v => v.toLocaleString() } },
                    x: { grid: { display: false } },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.raw;
                                const pct = ((v / total) * 100).toFixed(1);
                                return `${v.toLocaleString()} leads (${pct}% of open pipeline)`;
                            },
                        },
                    },
                },
                onHover: (evt, elements) => this._chartCursorHover(evt, elements),
                onClick: (evt, elements) => {
                    if (!elements.length) return;
                    const bucket = CrmDashboard.AGING_BUCKET_KEYS[elements[0].index];
                    if (bucket) this.openRecords("chart_aging", { bucket });
                },
            },
        });
    }

    // Pipeline by Owner — horizontal bar. Surfaces concentration risk.
    renderOwnerChart() {
        const canvas = this.chartRefs.ownerChart?.el;
        if (!canvas || !this.state.owner_pipeline.length) return;
        if (this.charts.owner) this.charts.owner.destroy();
        const labels = this.state.owner_pipeline.map(o => o.name);
        const counts = this.state.owner_pipeline.map(o => o.count);
        const total = counts.reduce((a, b) => a + b, 0) || 1;
        const colors = counts.map((_, i) => {
            const pct = counts[i] / total;
            return pct > 0.6 ? "#FF5A5F" : pct > 0.3 ? "#FFA48E" : "#7D7EAF";
        });
        this.charts.owner = new Chart(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Active Pipeline",
                    data: counts,
                    backgroundColor: colors,
                    borderRadius: 4,
                    barThickness: 22,
                }],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { beginAtZero: true, grid: {}, ticks: { callback: v => v.toLocaleString() } },
                    y: { grid: { display: false } },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.raw;
                                const pct = ((v / total) * 100).toFixed(1);
                                return `${v.toLocaleString()} leads (${pct}%)`;
                            },
                        },
                    },
                },
                onHover: (evt, elements) => this._chartCursorHover(evt, elements),
                onClick: (evt, elements) => {
                    if (!elements.length) return;
                    const owner = this.state.owner_pipeline[elements[0].index];
                    if (owner) this.openRecords("chart_owner", { owner_id: owner.id });
                },
            },
        });
    }

    // Pipeline by Source — donut. Empty data → empty state, no chart.
    renderSourceChart() {
        const canvas = this.chartRefs.sourceChart?.el;
        if (!canvas || !this.state.pipeline_by_source.length) return;
        if (this.charts.source) this.charts.source.destroy();
        const labels = this.state.pipeline_by_source.map(s => s.name);
        const counts = this.state.pipeline_by_source.map(s => s.count);
        this.charts.source = new Chart(canvas, {
            type: "doughnut",
            data: {
                labels,
                datasets: [{
                    data: counts,
                    backgroundColor: ["#7D7EAF","#BD85BA","#F78EAD","#FFA48E","#FFCA71","#CEA716","#1EC198","#0dcaf0","#a0a0a0","#6C63FF"],
                    borderWidth: 0,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: "55%",
                plugins: { legend: { position: "right", labels: { padding: 10, usePointStyle: true } } },
                onHover: (evt, elements) => this._chartCursorHover(evt, elements),
                onClick: (evt, elements) => {
                    if (!elements.length) return;
                    const source = this.state.pipeline_by_source[elements[0].index];
                    if (source) this.openRecords("chart_source", { source_name: source.name });
                },
            },
        });
    }

    renderSourceConversionChart() {
        const canvas = this.chartRefs.sourceConversionChart?.el;
        const data = this.state.kpi?.source_conversion;
        if (!canvas || !data || !data.length) return;
        if (this.charts.sourceConversion) this.charts.sourceConversion.destroy();
        const labels = data.map(d => d.source);
        const rates = data.map(d => d.rate);
        const totals = data.map(d => d.total);
        const colors = rates.map((r, i) => {
            // Green for high conversion, amber for medium, red for low
            if (r >= 20) return "#1EC198";
            if (r >= 10) return "#FFCA71";
            return "#FF5A5F";
        });
        this.charts.sourceConversion = new Chart(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{
                    label: "Conversion %",
                    data: rates,
                    backgroundColor: colors,
                    borderRadius: 4,
                    barThickness: 24,
                }],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { beginAtZero: true, max: 100, grid: {}, ticks: { callback: v => v + "%" } },
                    y: { grid: { display: false } },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const i = ctx.dataIndex;
                                return `${rates[i]}% conversion (${totals[i]} leads, ${data[i].won} won)`;
                            },
                        },
                    },
                },
                onHover: (evt, elements) => this._chartCursorHover(evt, elements),
                onClick: (evt, elements) => {
                    if (!elements.length) return;
                    const source = data[elements[0].index];
                    if (source) this.openRecords("chart_source", { source_name: source.source });
                },
            },
        });
    }

    renderFunnelChart() {
        const canvas = this.chartRefs.funnelChart?.el;
        if (!canvas || !this.state.funnel.length) return;
        if (this.charts.funnel) this.charts.funnel.destroy();
        const labels = this.state.funnel.map(s => s.name);
        const data = this.state.funnel.map(s => s.count);
        const maxVal = Math.max(...data, 1);
        const colors = data.map((v) => {
            const ratio = v / maxVal;
            if (ratio > 0.5) return "#7D7EAF";
            if (ratio > 0.2) return "#BD85BA";
            if (ratio > 0.05) return "#F78EAD";
            return "#FFA48E";
        });
        this.charts.funnel = new Chart(canvas, {
            type: "bar",
            data: {
                labels,
                datasets: [{ data, backgroundColor: colors, borderRadius: 4, barThickness: 28 }],
            },
            options: {
                indexAxis: "y",
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { beginAtZero: true, grid: {}, ticks: { callback: v => v.toLocaleString() } },
                    y: { grid: { display: false } },
                },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => {
                                const v = ctx.raw;
                                const pct = data[0] > 0 ? ((v / data[0]) * 100).toFixed(1) : 0;
                                return `${v.toLocaleString()} leads (${pct}% of total)`;
                            },
                        },
                    },
                },
                onHover: (evt, elements) => this._chartCursorHover(evt, elements),
                onClick: (evt, elements) => {
                    if (!elements.length) return;
                    const stage = this.state.funnel[elements[0].index];
                    if (stage) this.openRecords("chart_funnel", { stage_name: stage.name });
                },
            },
        });
    }

    formatCurrency(val) {
        return new Intl.NumberFormat("en-US", { style: "currency", currency: "AED", maximumFractionDigits: 0 }).format(val || 0);
    }

    formatNumber(val) {
        return new Intl.NumberFormat("en-US").format(val || 0);
    }

    formatAbbrev(val) {
        // 1.2K / 49K / 15M / 1.2B. Drops the trailing .0 only when redundant.
        const n = Number(val) || 0;
        const abs = Math.abs(n);
        if (abs >= 1e9) return (n / 1e9).toFixed(abs >= 1e10 ? 0 : 1).replace(/\.0$/, "") + "B";
        if (abs >= 1e6) return (n / 1e6).toFixed(abs >= 1e7 ? 0 : 1).replace(/\.0$/, "") + "M";
        if (abs >= 1e3) return (n / 1e3).toFixed(abs >= 1e4 ? 0 : 1).replace(/\.0$/, "") + "K";
        return String(Math.round(n));
    }

    daysColor(days) {
        if (days === null || days === undefined) return "#a0a0a0";
        if (days <= 3) return "#1EC198";
        if (days <= 7) return "#FFCA71";
        if (days <= 14) return "#FFA48E";
        return "#E74C3C";
    }

    daysLabel(days) {
        if (days === null || days === undefined) return "No activity";
        return days + "d";
    }
}

export class CrmDashboardScreen extends CrmDashboard {
    static autoTv = true;
}

registry.category("actions").add("crm_dashboard", CrmDashboard);
registry.category("actions").add("crm_dashboard_screen", CrmDashboardScreen);
