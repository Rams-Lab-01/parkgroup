/** @odoo-module **/
// Copyright 2026 SGC TECH AI � SGC Real Estate Executive Dashboard (v2)
import { Component, markup, useState, onWillStart, onMounted, onWillUnmount, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const THEME_KEY = "sgc-re-dashboard-theme";

export class RentalPropertyDashboard extends Component {
    static template = "sgc_offplan_rental_property_management.RentalPropertyDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.mapRef = useRef("mapViewport");
        this.unitMixChartRef = useRef("unitMixChart");
        this.sellThroughChartRef = useRef("sellThroughChart");
        this.collectionsChartRef = useRef("collectionsChart");
        this.escrowChartRef = useRef("escrowChart");
        this.agingChartRef = useRef("agingChart");

        this.state = useState({
            total_units: 0, sold_units: 0, available_units: 0,
            sell_through_pct: 0.0, sales_value: 0.0, avg_psf_sold: 0.0,
            collected: 0.0, balance_due: 0.0, collection_pct: 0.0,
            dso_days: 0.0, aged_overdue_units: 0, aged_overdue_amount: 0.0,
            admin_fees_total: 0.0,
            required_escrow: 0.0, allocated_escrow: 0.0, escrow_shortfall: 0.0,
            funded_pct: 0.0, recon_rate: 0.0, missing_source_count: 0,
            per_project: {}, project_map: {}, project_rows: [],
            unit_mix_labels: [], unit_mix_values: [],
            sell_through_labels: [], sell_through_series: { sold: [], available: [] },
            collections: [],
            escrow_labels: [], escrow_series: { required: [], allocated: [] },
            aging_labels: [], aging_data: [],
            watchlist: [],
            currency_symbol: "AED", company_name: "Park Group",
            cards: [], aging_undated: 0,
            theme: "light", loading: true, error: null,
        });
        this._dead = false;
        this._retryCount = 0;
        this._renderRetries = {};

        onWillStart(async () => {
            try {
                const stored = window.localStorage.getItem(THEME_KEY);
                this.state.theme = (stored === "dark" || stored === "light") ? stored :
                    (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
            } catch (_) { this.state.theme = "light"; }
            // Theme is applied reactively by the template via t-att-data-theme on
            // the dashboard root — nothing to set on <html> (which other apps share).
            await this.loadData();
        });

        onMounted(() => {
            this.renderUnitMixChart(); this.renderSellThroughChart();
            this.renderCollectionsChart(); this.renderEscrowChart();
            this.renderAgingChart(); this.renderMap();
        });

        onWillUnmount(() => {
            this._dead = true;
            if (this._leafletMap) { this._leafletMap.remove(); this._leafletMap = null; }
            ["_unitMixChart","_sellThroughChart","_collectionsChart","_escrowChart","_agingChart"].forEach(k => { if (this[k]) { this[k].dispose(); this[k]=null; } });
            ["_resizeUnitMix","_resizeSellThrough","_resizeCollections","_resizeEscrow","_resizeAging"].forEach(k => { if (this[k]) window.removeEventListener("resize", this[k]); });
        });
    }
    async loadData() {
        try {
            const payload = await this.orm.call("property.details", "get_development_kpis", []);
            // NOTE: this.env.company is undefined in the Odoo 19 web client
            // (there is no company in the action environment), which used to throw
            // here and abort the whole dashboard into an empty state. The server
            // payload carries the company context instead.
            this.state.currency_symbol = payload.currency_symbol || "AED";
            this.state.company_name = payload.company_name || "Park Group";
            Object.assign(this.state, {
                total_units: payload.total_units||0, sold_units: payload.sold_units||0, available_units: payload.available_units||0,
                sell_through_pct: payload.sell_through_pct||0, sales_value: payload.sales_value||0, avg_psf_sold: payload.avg_psf_sold||0,
                collected: payload.collected||0, balance_due: payload.balance_due||0, collection_pct: payload.collection_pct||0,
                dso_days: payload.dso_days||0,
                aged_overdue_units: payload.aged_overdue_units||0, aged_overdue_amount: payload.aged_overdue_amount||0,
                admin_fees_total: payload.admin_fees_total||0,
                required_escrow: payload.required_escrow||0, allocated_escrow: payload.allocated_escrow||0,
                escrow_shortfall: payload.escrow_shortfall||0, funded_pct: payload.funded_pct||0,
                recon_rate: payload.recon_rate||0, missing_source_count: payload.missing_source_count||0,
            });
            this.state.per_project = payload.per_project||{};
            this.state.project_map = payload.project_map||{};
            this.state.unit_mix_labels = payload.unit_mix_labels || payload.unit_mix?.[0] || [];
            this.state.unit_mix_values = payload.unit_mix_values || payload.unit_mix?.[1] || [];
            // Flatten per-project dict into a renderable array for the table.
            this.state.project_rows = Object.entries(payload.per_project || {}).map(([code, rec]) => ({
                code: code,
                units: rec.units || 0,
                sold: rec.sold || 0,
                available: (rec.units || 0) - (rec.sold || 0),
                sell_pct: rec.sell_pct || 0,
                sales_value: rec.sales_value || 0,
                collected: rec.collected || 0,
                required_escrow: rec.required_escrow || 0,
                allocated_escrow: rec.allocated_escrow || 0,
                variance: rec.variance || 0,
                recon_rate: rec.recon_rate || 0,
                funded_pct: rec.funded_pct || 0,
                lat: payload.project_map?.[code]?.lat || 0,
                lon: payload.project_map?.[code]?.lon || 0,
            })).sort((a, b) => b.units - a.units);
            const sLabels = [], sSold = [], sAvail = [];
            for (const [code, rec] of Object.entries(payload.per_project||{})) {
                sLabels.push(`${code} (${rec.units||0} units)`);
                sSold.push(rec.sold||0); sAvail.push((rec.units||0)-(rec.sold||0));
            }
            this.state.sell_through_labels = sLabels;
            this.state.sell_through_series = { sold: sSold, available: sAvail };
            try {
                // formatted_read_group returns dicts; the month groupby key is
                // "payment_date:month" and its value is a pair
                // ["2024-04-01", "April 2024"] — not a plain date under "payment_date".
                const cols = await this.orm._read_group("sale.contract.installment", [["state","=","paid"],["payment_date","!=",false]], ["payment_date:month"], ["amount:sum"]);
                const collMap = new Map();
                for (const r of cols) {
                    const pair = r["payment_date:month"] ?? r.payment_date;
                    const raw = Array.isArray(pair) ? pair[0] : pair;
                    const key = raw ? new Date(raw).toLocaleString("default",{month:"short",year:"numeric"}) : "Unknown";
                    collMap.set(key, (collMap.get(key)||0)+(Number(r["amount:sum"])||0));
                }
                const sortKey = (k) => {
                    const m = /^([A-Za-z]{3})\s+(\d{4})$/.exec(String(k));
                    if (!m) return Number.MAX_SAFE_INTEGER; // "Unknown" sorts last
                    return new Date(`${m[2]} ${m[1]} 1`).getTime();
                };
                const entries = Array.from(collMap.entries());
                entries.sort((a, b) => sortKey(a[0]) - sortKey(b[0]));
                this.state.collections = entries;
            } catch(_) { this.state.collections=[]; }
            try {
                // formatted_read_group returns project_id as [id, display_name] —
                // use the display name directly (a name lookup keyed on p.id broke
                // because p.id is the whole [id, name] array).
                const escRows = await this.orm._read_group("escrow.allocation", [], ["project_id"], ["required_amount:sum","allocated_amount:sum"]);
                const escMap = {};
                for (const r of escRows) {
                    const proj = r.project_id;
                    const label = Array.isArray(proj) && proj[1] ? proj[1]
                        : (proj ? `Project ${proj[0] || proj}` : "Unassigned");
                    escMap[label]={required:Number(r["required_amount:sum"])||0, allocated:Number(r["allocated_amount:sum"])||0};
                }
                this.state.escrow_labels = Object.keys(escMap);
                this.state.escrow_series = {
                    required:Object.values(escMap).map(x=>x.required),
                    allocated:Object.values(escMap).map(x=>x.allocated)
                };
            } catch(_) { this.state.escrow_labels=[]; this.state.escrow_series={required:[],allocated:[]}; }
            // Real aging buckets computed server-side (no placeholder zeros).
            const buckets = (payload.aging_buckets && payload.aging_buckets.length)
                ? payload.aging_buckets
                : [];
            this.state.aging_labels = buckets.map(b => b.label);
            this.state.aging_data = buckets.map(b => ({label:b.label, count:b.count||0, amount:b.amount||0}));
            this.state.aging_undated = payload.undated_balance || 0;
            // Counts come from the server (payload.watchlist_counts) so the watchlist can
            // never display a hardcoded 0. variance_amount is ALLOCATED - REQUIRED, so
            // negative = under-allocated and positive = over-allocated.
            const wc = payload.watchlist_counts || {};
            this.state.watchlist = [
                {label:"Reconciled",count:wc.reconciled||0,domain:[["has_source_data","=",true],["variance_amount","<=",0.01],["variance_amount",">=",-0.01]]},
                {label:"Under-allocated",count:wc.under_allocated||0,domain:[["variance_amount","<",-0.01]]},
                {label:"Over-allocated",count:wc.over_allocated||0,domain:[["variance_amount",">",0.01]]},
                {label:"Awaiting source",count:wc.awaiting_source||0,domain:[["has_source_data","=",false]]},
            ];
            this.state.cards = this._buildCards(payload);
            this.state.error = null;
            this.state.loading = false;
            this._retryCount = 0;
            this._renderRetries = {};
            this.renderUnitMixChart(); this.renderSellThroughChart(); this.renderCollectionsChart(); this.renderEscrowChart(); this.renderAgingChart();
            this.renderMap();
        } catch(e) {
            console.error("[Property Dashboard] loadData error:", e);
            this.state.loading = false;
            this.state.error = (e && (e.data?.message || e.message)) || "Dashboard data could not be loaded.";
            if (!this._dead) this._scheduleRetry();
        }
    }

    /** Re-run loadData after a failure, capped so a persistent outage cannot
     *  hammer the server with RPCs. */
    _scheduleRetry() {
        if (this._dead) return;
        this._retryCount = (this._retryCount || 0) + 1;
        if (this._retryCount > 5) { console.warn("[Property Dashboard] giving up after", this._retryCount - 1, "retries"); return; }
        setTimeout(() => { if (!this._dead) this.loadData(); }, 30000);
    }

    /** Manual retry from the error panel's Retry button. */
    retryLoad() {
        this._retryCount = 0;
        this.state.error = null;
        this.state.loading = true;
        this.loadData();
    }

    /** Guarded chart/map render: retries a capped number of times while the
     *  DOM ref or library (echarts/leaflet) is still unavailable, and stops
     *  permanently once the component is unmounted. */
    _renderWhenReady(name, fn) {
        if (this._dead) return;
        this._renderRetries = this._renderRetries || {};
        const n = (this._renderRetries[name] || 0);
        if (n >= 50) { console.warn("[Property Dashboard] giving up rendering", name); return; }
        this._renderRetries[name] = n + 1;
        setTimeout(() => { if (!this._dead) fn.call(this); }, 200);
    }

    /** Builds the 18 KPI cards. Every value is derived from the server payload;
     *  nothing is hardcoded so the dashboard can never show stale/fake numbers. */
    _buildCards(payload) {
        const SYM = this.state.currency_symbol || "AED";
        const num = (v) => Number(v) || 0;
        const amt = (v) => this._formatAmt(num(v));
        const money = (v) => `${SYM} ${amt(v)}`;
        const pct = (v) => `${num(v).toFixed(1)}%`;
        const cnt = (v) => String(Math.round(num(v)));
        const ICON = {
            units: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21V9l9-6 9 6v12"/><path d="M9 21v-7h6v7"/></svg>'),
            sold: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/></svg>'),
            available: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'),
            pct: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2v20"/></svg>'),
            money: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-7"/></svg>'),
            wallet: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>'),
            clock: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>'),
            bank: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M3 10h18M5 6l7-4 7 4M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/></svg>'),
            alert: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/></svg>'),
            check: markup('<svg aria-hidden="true" focusable="false" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>'),};
        return [
            // Row A - inventory and sales (tone drives the icon chip colour)
            {label:"Total Units", value:cnt(payload.total_units), sub:"All unit records", icon:ICON.units, tone:"blue", action:"viewAllProperties"},
            {label:"Sold Units", value:cnt(payload.sold_units), sub:"Units with a signed contract", icon:ICON.sold, tone:"green", action:"viewSoldProperties"},
            {label:"Available Units", value:cnt(payload.available_units), sub:"Still on the market", icon:ICON.available, tone:"cyan", action:"viewAvailableProperties"},
            {label:"Sell-Through", value:pct(payload.sell_through_pct), sub:"Sold / Total units", icon:ICON.pct, tone:"blue", action:"viewAllProperties"},
            {label:"Sales Value", value:money(payload.sales_value), sub:"Signed contract value", icon:ICON.money, tone:"green", action:"viewProjects"},
            {label:"Avg PSF (sold)", value:`${num(payload.avg_psf_sold).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})} ${SYM}/sqft`, sub:"Contract price / unit area", icon:ICON.money, tone:"amber", action:"viewSoldProperties"},
            // Row B - collections and receivables
            {label:"Collected", value:money(payload.collected), sub:"Paid installments", icon:ICON.wallet, tone:"green", action:"viewProjects"},
            {label:"Balance Due", value:money(payload.balance_due), sub:"Still outstanding", icon:ICON.money, tone:"red", action:"viewOutstanding"},
            {label:"Collection Rate", value:pct(payload.collection_pct), sub:"Collected / Sales value", icon:ICON.pct, tone:"blue", action:"viewProjects"},
            {label:"DSO", value:`${Math.round(num(payload.dso_days))} days`, sub:"Balance / Sales x 365", icon:ICON.clock, tone:"cyan", action:"viewOutstanding"},
            {label:"Aged > 90 Days", value:cnt(payload.aged_overdue_units), sub:"No activity in 90+ days", icon:ICON.alert, tone:"red", action:"viewAgedOverdue"},
            {label:"Admin Fees", value:money(payload.admin_fees_total), sub:"Billed across all units", icon:ICON.money, tone:"amber", action:"viewProjects"},
            // Row C - escrow compliance
            {label:"Expected Escrow", value:money(payload.required_escrow), sub:"Required allocations", icon:ICON.bank, tone:"blue", action:"viewAllAllocations"},
            {label:"Allocated Escrow", value:money(payload.allocated_escrow), sub:"Funds placed in escrow", icon:ICON.bank, tone:"cyan", action:"viewWithSource"},
            {label:"Escrow Shortfall", value:money(payload.escrow_shortfall), sub:"Required - Allocated", icon:ICON.alert, tone:"red", action:"viewUnderAllocated"},
            {label:"Funded Rate", value:pct(payload.funded_pct), sub:"Allocated / Required", icon:ICON.pct, tone:"green", action:"viewWithSource"},
            {label:"Reconciliation Rate", value:pct(payload.recon_rate), sub:"Reconciled / Allocations", icon:ICON.check, tone:"green", action:"viewReconciled"},
            {label:"Missing Source", value:cnt(payload.missing_source_count), sub:"Awaiting source data", icon:ICON.alert, tone:"amber", action:"viewAwaitingSource"},
        ];
    }

    formatCurrency(amount) { const sym=this.state.currency_symbol||""; return sym?`${sym} ${this._formatAmt(amount)}`:this._formatAmt(amount); }
    domainString(wl){ try { return JSON.stringify(wl.domain); } catch(_){ return "[]"; } }
    formatPct(v) { return (Number(v)||0).toFixed(1)+"%"; }
    _formatAmt(a) { const n=Number(a)||0; const abs=Math.abs(n); if(abs>=1_000_000_000) return(n/1_000_000_000).toFixed(1)+"B"; if(abs>=1_000_000) return(n/1_000_000).toFixed(1)+"M"; if(abs>=1_000) return(n/1_000).toFixed(1)+"K"; return n.toLocaleString("en-US"); }
    _esc(s){return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");}
    open(model,name,domain,target="current"){this.action.doAction({type:"ir.actions.act_window",name,res_model:model,view_mode:"list,form",views:[[false,"list"],[false,"form"]],target,domain});}

    renderUnitMixChart(){
        if(this._dead) return;
        if(!this.unitMixChartRef.el||!window.echarts){this._renderWhenReady("unitMix",this.renderUnitMixChart);return;}
        const dark=this.state.theme==="dark";
        const colors=dark?["#fbbf24","#60a5fa","#34d399","#fb923c","#a78bfa"]:["#f59e0b","#1e40af","#10b981","#f97316","#8b5cf6"];
        if(this._unitMixChart) this._unitMixChart.dispose();
        const chart=window.echarts.init(this.unitMixChartRef.el,null,{renderer:"canvas"});
        const labels=this.state.unit_mix_labels.length?this.state.unit_mix_labels:["Studio","1BR","2BR","3BR","N-A"];
        const values=this.state.unit_mix_values.length?this.state.unit_mix_values:[0,0,0,0,0];
        chart.setOption({tooltip:{trigger:"item",backgroundColor:dark?"#131b35":"#ffffff",borderColor:dark?"#243157":"#d6dae6",textStyle:{color:dark?"#f1f5f9":"#0f172a"}},legend:{bottom:0,textStyle:{color:dark?"#94a3b8":"#475569"}},series:[{type:"pie",radius:["40%","70%"],center:["50%","50%"],data:labels.map((l,i)=>({name:l,value:values[i]||0,itemStyle:{color:colors[i]||"#94a3b8"}})),label:{show:false},emphasis:{itemStyle:{shadowBlur:10,shadowColor:"rgba(0,0,0,0.2)"}}}]});
        this._unitMixChart=chart; this._resizeUnitMix=()=>chart.resize(); window.addEventListener("resize",this._resizeUnitMix);
    }
    renderSellThroughChart(){
        if(this._dead) return;
        if(!this.sellThroughChartRef.el||!window.echarts){this._renderWhenReady("sellThrough",this.renderSellThroughChart);return;}
        const dark=this.state.theme==="dark";
        if(this._sellThroughChart) this._sellThroughChart.dispose();
        const chart=window.echarts.init(this.sellThroughChartRef.el,null,{renderer:"canvas"});
        const colors={sold:dark?"#f87171":"#ef4444",available:dark?"#60a5fa":"#1e40af"};
        chart.setOption({tooltip:{trigger:"axis",axisPointer:{type:"shadow"},backgroundColor:dark?"#131b35":"#ffffff",borderColor:dark?"#243157":"#d6dae6",textStyle:{color:dark?"#f1f5f9":"#0f172a"}},legend:{data:["Sold","Available"],bottom:0,textStyle:{color:dark?"#94a3b8":"#475569"}},xAxis:{type:"category",data:this.state.sell_through_labels,axisLabel:{color:dark?"#94a3b8":"#64748b"}},yAxis:{type:"value",minInterval:1,axisLabel:{color:dark?"#94a3b8":"#64748b"}},series:[{name:"Sold",type:"bar",data:this.state.sell_through_series.sold,itemStyle:{color:colors.sold,borderRadius:[4,4,0,0]}},{name:"Available",type:"bar",data:this.state.sell_through_series.available,itemStyle:{color:colors.available,borderRadius:[4,4,0,0]}}],grid:{left:40,right:16,top:16,bottom:40}});
        this._sellThroughChart=chart; this._resizeSellThrough=()=>chart.resize(); window.addEventListener("resize",this._resizeSellThrough);
    }

    renderCollectionsChart(){
        if(this._dead) return;
        if(!this.collectionsChartRef.el||!window.echarts){this._renderWhenReady("collections",this.renderCollectionsChart);return;}
        const dark=this.state.theme==="dark";
        if(this._collectionsChart) this._collectionsChart.dispose();
        const chart=window.echarts.init(this.collectionsChartRef.el,null,{renderer:"canvas"});
        const months=this.state.collections.map(c=>c[0]); const paid=this.state.collections.map(c=>c[1]);
        chart.setOption({tooltip:{trigger:"axis",axisPointer:{type:"shadow"},backgroundColor:dark?"#131b35":"#ffffff",borderColor:dark?"#243157":"#d6dae6",textStyle:{color:dark?"#f1f5f9":"#0f172a"}},xAxis:{type:"category",data:months,axisLabel:{color:dark?"#94a3b8":"#64748b"}},yAxis:{type:"value",axisLabel:{color:dark?"#94a3b8":"#64748b",formatter:v=>this._shortNum(v)}},series:[{name:"Paid Collections",type:"bar",data:paid,itemStyle:{color:dark?"#34d399":"#10b981",borderRadius:[4,4,0,0]}}],grid:{left:56,right:16,top:16,bottom:40}});
        this._collectionsChart=chart; this._resizeCollections=()=>chart.resize(); window.addEventListener("resize",this._resizeCollections);
    }

    renderEscrowChart(){
        if(this._dead) return;
        if(!this.escrowChartRef.el||!window.echarts){this._renderWhenReady("escrow",this.renderEscrowChart);return;}
        const dark=this.state.theme==="dark";
        if(this._escrowChart) this._escrowChart.dispose();
        const chart=window.echarts.init(this.escrowChartRef.el,null,{renderer:"canvas"});
        chart.setOption({tooltip:{trigger:"axis",axisPointer:{type:"shadow"},backgroundColor:dark?"#131b35":"#ffffff",borderColor:dark?"#243157":"#d6dae6",textStyle:{color:dark?"#f1f5f9":"#0f172a"}},legend:{data:["Required","Allocated"],bottom:0,textStyle:{color:dark?"#94a3b8":"#475569"}},xAxis:{type:"category",data:this.state.escrow_labels,axisLabel:{color:dark?"#94a3b8":"#64748b"}},yAxis:{type:"value",minInterval:1000000,axisLabel:{color:dark?"#94a3b8":"#64748b",formatter:v=>this._shortNum(v)}},series:[{name:"Required",type:"bar",data:this.state.escrow_series.required,itemStyle:{color:dark?"#fbbf24":"#f59e0b",borderRadius:[4,4,0,0]}},{name:"Allocated",type:"bar",data:this.state.escrow_series.allocated,itemStyle:{color:dark?"#60a5fa":"#1e40af",borderRadius:[4,4,0,0]}}],grid:{left:56,right:16,top:16,bottom:40}});
        this._escrowChart=chart; this._resizeEscrow=()=>chart.resize(); window.addEventListener("resize",this._resizeEscrow);
    }

    renderAgingChart(){
        if(this._dead) return;
        if(!this.agingChartRef.el||!window.echarts){this._renderWhenReady("aging",this.renderAgingChart);return;}
        const dark=this.state.theme==="dark";
        if(this._agingChart) this._agingChart.dispose();
        const chart=window.echarts.init(this.agingChartRef.el,null,{renderer:"canvas"});
        const labels=this.state.aging_labels; const data=this.state.aging_data.map(d=>d.count);
        chart.setOption({tooltip:{trigger:"axis",axisPointer:{type:"shadow"},backgroundColor:dark?"#131b35":"#ffffff",borderColor:dark?"#243157":"#d6dae6",textStyle:{color:dark?"#f1f5f9":"#0f172a"}},xAxis:{type:"category",data:labels,axisLabel:{color:dark?"#94a3b8":"#64748b"}},yAxis:{type:"value",minInterval:1,axisLabel:{color:dark?"#94a3b8":"#64748b"}},series:[{name:"Units",type:"bar",data:data,itemStyle:{color:dark?"#fbbf24":"#f59e0b",borderRadius:[4,4,0,0]}}],grid:{left:56,right:16,top:16,bottom:40}});
        this._agingChart=chart; this._resizeAging=()=>chart.resize(); window.addEventListener("resize",this._resizeAging);
    }

    _shortNum(v){if(v>=1_000_000) return(v/1_000_000).toFixed(0)+"M"; if(v>=1_000) return(v/1_000).toFixed(0)+"K"; return String(v);}

    renderMap(){
        if(this._dead) return;
        const el=this.mapRef.el; if(!el) { this._renderWhenReady("map",this.renderMap); return; }
        if(!window.L){this._renderWhenReady("map",this.renderMap);return;}
        if(this._leafletMap){this._leafletMap.remove();this._leafletMap=null;}
        const map=window.L.map(el,{zoomControl:false,scrollWheelZoom:true,minZoom:6,maxZoom:18,zoomSnap:0.5}).setView([24.5,54.5],7);
        window.L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",{attribution:"Tiles &copy; Esri",maxZoom:19}).addTo(map);
        window.L.control.zoom({position:"topright"}).addTo(map);
        for(const [code,rec] of Object.entries(this.state.project_map||{})){
            const lat=rec.lat||0, lon=rec.lon||0; if(!lat||!lon) continue;
            const icon=window.L.divIcon({className:"sgc-leaflet-pin",html:`<div class="sgc-pin-wrap"><div class="sgc-pin-pulse" style="background:#1e40af;"></div><div class="sgc-pin-halo" style="background:#1e40af;"></div><div class="sgc-pin-core" style="background:#1e40af;"></div></div>`,iconSize:[28,28],iconAnchor:[14,14]});
            window.L.marker([lat,lon],{icon}).addTo(map).bindPopup(`<div class="sgc-popup"><div class="sgc-popup__city"><b>${this._esc(rec.name||code)}</b></div>${rec.city?`<div class="sgc-popup__city">${this._esc(rec.city)}</div>`:""}<div class="sgc-popup__count">${rec.units||0} units &middot; ${rec.count||0} sold &middot; ${(rec.units||0)-(rec.count||0)} available</div></div>`,{className:"sgc-popup-wrapper",closeButton:false});
        }
        this._leafletMap=map; requestAnimationFrame(()=>{if(this._leafletMap) this._leafletMap.invalidateSize();});
    }

    toggleTheme(){
        const next=this.state.theme==="light"?"dark":"light";
        // Reactive: the template binds t-att-data-theme="state.theme" on the
        // dashboard root; CSS tokens switch with it. No <html> mutation needed.
        this.state.theme=next;
        try{window.localStorage.setItem(THEME_KEY,next);}catch(_){}
        setTimeout(()=>{this.renderUnitMixChart();this.renderSellThroughChart();this.renderCollectionsChart();this.renderEscrowChart();this.renderAgingChart();this.renderMap();},0);
    }

    /* ===================== Accessibility helpers ===================== */

    /** Screen-reader text alternative for the Unit Mix donut. */
    ariaUnitMix(){
        const l=this.state.unit_mix_labels||[], v=this.state.unit_mix_values||[];
        if(!l.length) return "Unit mix chart, no data available.";
        return "Unit mix: " + l.map((label,i)=>`${label} ${v[i]||0}`).join(", ") + ".";
    }
    /** Screen-reader text alternative for Sell-Through by Project. */
    ariaSellThrough(){
        const l=this.state.sell_through_labels||[], s=this.state.sell_through_series||{sold:[],available:[]};
        if(!l.length) return "Sell-through by project chart, no data available.";
        return "Sell-through by project: " + l.map((label,i)=>`${label}: ${s.sold[i]||0} sold, ${s.available[i]||0} available`).join("; ") + ".";
    }
    /** Screen-reader text alternative for Monthly Collections. */
    ariaCollections(){
        const c=this.state.collections||[];
        if(!c.length) return "Monthly collections chart, no data available.";
        return "Monthly collections: " + c.map(([month,amt])=>`${month} ${this.formatCurrency(amt)}`).join("; ") + ".";
    }
    /** Screen-reader text alternative for Escrow Required vs Allocated. */
    ariaEscrow(){
        const l=this.state.escrow_labels||[], s=this.state.escrow_series||{required:[],allocated:[]};
        if(!l.length) return "Escrow chart, no data available.";
        return "Escrow by project: " + l.map((label,i)=>`${label}: required ${this.formatCurrency(s.required[i]||0)}, allocated ${this.formatCurrency(s.allocated[i]||0)}`).join("; ") + ".";
    }
    /** Screen-reader text alternative for Receivables Aging. */
    ariaAging(){
        const d=this.state.aging_data||[];
        const parts=d.map(x=>`${x.label}: ${x.count} units, ${this.formatCurrency(x.amount)}`);
        if(this.state.aging_undated) parts.push(`undated ${this.formatCurrency(this.state.aging_undated)}`);
        if(!parts.length) return "Receivables aging chart, no data available.";
        return "Receivables aging: " + parts.join("; ") + ".";
    }
    /** Screen-reader text alternative for the project map. */
    ariaMap(){
        const rows=(this.state.project_rows||[]).filter(r=>r.lat&&r.lon);
        if(!rows.length) return "Project map, no locations available.";
        return "Map of " + rows.length + " projects: " + rows.map(r=>`${r.code}, ${r.units} units, ${r.sold} sold`).join("; ") + ".";
    }

    /** Keyboard activation for KPI cards (role="button" divs). Reads the action from dataset. */
    onCardClick(ev){
        const action = ev.currentTarget.dataset.action;
        if (action && typeof this[action] === "function") this[action]();
    }
    onCardKey(ev){
        if (ev.key === "Enter" || ev.key === " " || ev.key === "Spacebar") {
            ev.preventDefault();
            const action = ev.currentTarget.dataset.action;
            if (action && typeof this[action] === "function") this[action]();
        }
    }
    /** Keyboard activation for watchlist rows (role="button" divs). Reads label/domain from dataset. */
    onWatchlistClick(ev){
        const label = ev.currentTarget.dataset.label;
        let domain;
        try { domain = JSON.parse(ev.currentTarget.dataset.domain); } catch (_) { return; }
        this.open("escrow.allocation", label, domain);
    }
    onWatchlistKey(ev){
        if (ev.key === "Enter" || ev.key === " " || ev.key === "Spacebar") {
            ev.preventDefault();
            const label = ev.currentTarget.dataset.label;
            let domain;
            try { domain = JSON.parse(ev.currentTarget.dataset.domain); } catch (_) { return; }
            this.open("escrow.allocation", label, domain);
        }
    }
    onRowClick(ev){ this.viewProjects(); }
    /** Keyboard activation for table rows (role="button"). */
    onRowKey(ev){
        if(ev.key==="Enter"||ev.key===" "||ev.key==="Spacebar"){
            ev.preventDefault();
            this.viewProjects();
        }
    }

    viewAllProperties(){this.open("property.details","Properties",[]);}
    viewSoldProperties(){this.open("property.details","Sold Properties",[["state","in",["sold","completed"]]]);}
    viewAvailableProperties(){this.open("property.details","Available Properties",[["state","=","available"]]);}
    viewProjects(){this.open("property.project","Projects",[]);}
    viewCustomers(){this.open("res.partner","Customers",[["user_type","=","customer"]]);}
    viewLandlords(){this.open("res.partner","Landlords",[["user_type","=","landlord"]]);}

    // variance_amount = allocated - required, so NEGATIVE = under-allocated.
    viewReconciled(){this.open("escrow.allocation","Reconciled Allocations",[["has_source_data","=",true],["variance_amount","<=",0.01],["variance_amount",">=",-0.01]]);}
    viewUnderAllocated(){this.open("escrow.allocation","Under-Allocated",[["variance_amount","<",-0.01]]);}
    viewOverAllocated(){this.open("escrow.allocation","Over-Allocated",[["variance_amount",">",0.01]]);}
    viewAwaitingSource(){this.open("escrow.allocation","Awaiting Source",[["has_source_data","=",false]]);}
    viewAllAllocations(){this.open("escrow.allocation","Escrow Allocations",[]);}
    viewWithSource(){this.open("escrow.allocation","Allocations With Source",[["has_source_data","=",true]]);}
    viewOutstanding(){this.open("sale.contract","Outstanding Balance",[["balance_due",">",0.01]]);}

    viewAgedOverdue(){const d90=new Date();d90.setDate(d90.getDate()-90);const iso=d90.toISOString().slice(0,10);this.open("sale.contract","Aged Overdue",[["balance_due",">",0.01],["last_activity_date","<=",iso]]);}
}

const dashboardActions = registry.category("actions");
if (dashboardActions.contains("property_dashboard")) console.debug("[rental_property_dashboard] already present");
else { dashboardActions.add("property_dashboard", RentalPropertyDashboard); console.log("[rental_property_dashboard] registered"); }