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
            leaderboard: { top: [], me: null },
        });
        this.chartRefs = {
            stageChart: useRef("stageChart"),
            monthlyChart: useRef("monthlyChart"),
            funnelChart: useRef("funnelChart"),
            agingChart: useRef("agingChart"),
            ownerChart: useRef("ownerChart"),
            sourceChart: useRef("sourceChart"),
        };
        this.charts = {};
        this._chartsReady = false;

        onWillUnmount(() => {
            this.destroyCharts();
        });

        onMounted(async () => {
            await this.loadDashboard();
        });
    }

    async loadDashboard(userId) {
        this.destroyCharts();
        this.state.loading = true;
        try {
            const params = userId ? [userId] : [];
            const data = await this.orm.call("crm.dashboard", "get_dashboard_data", params);
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

        // Wait for OWL to re-render with data, then render charts
        await new Promise((resolve) => setTimeout(resolve, 50));
        await this._ensureChartJs();
        this.renderCharts();
    }

    async _ensureChartJs() {
        if (typeof Chart === "undefined") {
            await loadJS("/web/static/lib/Chart/Chart.js");
        }
    }

    async onFilterChange(ev) {
        const val = ev.target.value;
        const userId = val ? parseInt(val) : null;
        await this.loadDashboard(userId);
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
                "crm.dashboard", "open_records", [kind, params || {}, this.state.selectedUserId]
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
        this.renderStageChart();
        this.renderMonthlyChart();
        this.renderFunnelChart();
        this.renderAgingChart();
        this.renderOwnerChart();
        this.renderSourceChart();
    }

    renderStageChart() {
        const canvas = this.chartRefs.stageChart?.el;
        if (!canvas || !this.state.stages.length) return;
        if (this.charts.stage) this.charts.stage.destroy();
        const labels = this.state.stages.map(s => s.name);
        const data = this.state.stages.map(s => s.count);
        const colors = ["#7D7EAF", "#BD85BA", "#F78EAD", "#FFA48E", "#FFCA71", "#CEA716", "#1EC198", "#a0a0a0", "#6C63FF", "#E74C3C"];
        this.charts.stage = new Chart(canvas, {
            type: "doughnut",
            data: {
                labels,
                datasets: [{ data, backgroundColor: colors.slice(0, data.length), borderWidth: 0 }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: "right", labels: { padding: 12, usePointStyle: true } } },
                cutout: "55%",
                onHover: (evt, elements) => this._chartCursorHover(evt, elements),
                onClick: (evt, elements) => {
                    if (!elements.length) return;
                    const stage = this.state.stages[elements[0].index];
                    if (stage) this.openRecords("chart_stage", { stage_name: stage.name });
                },
            },
        });
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
                    y: { beginAtZero: true, grid: { color: "#f0f0f0" } },
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
                    y: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { callback: v => v.toLocaleString() } },
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
                    x: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { callback: v => v.toLocaleString() } },
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
                    x: { beginAtZero: true, grid: { color: "#f0f0f0" }, ticks: { callback: v => v.toLocaleString() } },
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

registry.category("actions").add("crm_dashboard", CrmDashboard);
