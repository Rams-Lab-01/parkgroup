import re

p = 'rental_property_dashboard.js'
s = open(p, encoding='utf-8', errors='replace').read()

# ---------------------------------------------------------------- 1
# Drop the orphaned duplicate block that was appended after registration.
anchor = 'else { dashboardActions.add("property_dashboard", RentalPropertyDashboard); console.log("[rental_property_dashboard] registered"); }'
idx = s.find(anchor)
assert idx != -1, 'registration anchor not found'
tail = s[idx + len(anchor):]
# the orphan begins at the next line that is indented deeply after the registration
m = re.search(r'\n\s{8,}this\.state\.watchlist', tail)
assert m, 'orphan block not found'
orphan = tail[m.start():]
s = s[:idx + len(anchor)]
print('removed orphan block of', len(orphan), 'chars')

# ---------------------------------------------------------------- 2
# Replace the fabricated aging block with real server-provided buckets.
old_aging = """            const aged = payload.aged_overdue_units||0;
            this.state.aging_labels = ["> 180 days","91-180 days","61-90 days","31-60 days","0-30 days"];
            this.state.aging_data = [
                {label:"> 180 days", count:aged, amount:payload.aged_overdue_amount||0},
                {label:"91-180 days",count:0,amount:0},
                {label:"61-90 days",count:0,amount:0},
                {label:"31-60 days",count:0,amount:0},
                {label:"0-30 days",count:0,amount:0}
            ];
"""
new_aging = """            // Real aging buckets computed server-side (no placeholder zeros).
            const buckets = (payload.aging_buckets && payload.aging_buckets.length)
                ? payload.aging_buckets
                : [];
            this.state.aging_labels = buckets.map(b => b.label);
            this.state.aging_data = buckets.map(b => ({label:b.label, count:b.count||0, amount:b.amount||0}));
            this.state.aging_undated = payload.undated_balance || 0;
"""
assert old_aging in s, 'aging block not found'
s = s.replace(old_aging, new_aging)
print('aging block now driven by server buckets')

# ---------------------------------------------------------------- 3
# Insert the computed (non-hardcoded) 18 KPI cards before loading=false.
old_tail = """            this.state.loading = false;
            this.renderUnitMixChart(); this.renderSellThroughChart(); this.renderCollectionsChart(); this.renderEscrowChart(); this.renderAgingChart();"""
new_tail = """            this.state.cards = this._buildCards(payload);
            this.state.loading = false;
            this.renderUnitMixChart(); this.renderSellThroughChart(); this.renderCollectionsChart(); this.renderEscrowChart(); this.renderAgingChart();
            this.renderMap();"""
assert old_tail in s, 'loadData tail not found'
s = s.replace(old_tail, new_tail, 1)
print('loadData tail now builds cards from payload')

# ---------------------------------------------------------------- 4
# Add the _buildCards helper right before formatCurrency().
anchor2 = '    formatCurrency(amount) {'
assert anchor2 in s, 'formatCurrency anchor not found'

helper = '''    /** Builds the 18 KPI cards. Every value is derived from the server payload;
     *  nothing is hardcoded so the dashboard can never show stale/fake numbers. */
    _buildCards(payload) {
        const SYM = this.state.currency_symbol || "AED";
        const num = (v) => Number(v) || 0;
        const amt = (v) => this._formatAmt(num(v));
        const money = (v) => `${SYM} ${amt(v)}`;
        const pct = (v) => `${num(v).toFixed(1)}%`;
        const cnt = (v) => String(Math.round(num(v)));
        const ICON = {
            units: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21V9l9-6 9 6v12"/><path d="M9 21v-7h6v7"/></svg>',
            sold: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/></svg>',
            available: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
            pct: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2v20"/></svg>',
            money: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 14l4-4 4 4 5-7"/></svg>',
            wallet: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/></svg>',
            clock: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>',
            bank: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 21h18M3 10h18M5 6l7-4 7 4M4 10v11M20 10v11M8 14v3M12 14v3M16 14v3"/></svg>',
            alert: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/></svg>',
            check: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
        };
        return [
            // Row A - inventory and sales
            {label:"Total Units", value:cnt(payload.total_units), sub:"All unit records", icon:ICON.units, action:"viewAllProperties"},
            {label:"Sold Units", value:cnt(payload.sold_units), sub:"Units with a signed contract", icon:ICON.sold, action:"viewSoldProperties"},
            {label:"Available Units", value:cnt(payload.available_units), sub:"Still on the market", icon:ICON.available, action:"viewAvailableProperties"},
            {label:"Sell-Through", value:pct(payload.sell_through_pct), sub:"Sold / Total units", icon:ICON.pct, action:"viewAllProperties"},
            {label:"Sales Value", value:money(payload.sales_value), sub:"Signed contract value", icon:ICON.money, action:"viewProjects"},
            {label:"Avg PSF (sold)", value:`${num(payload.avg_psf_sold).toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2})} ${SYM}/sqft`, sub:"Contract price / unit area", icon:ICON.money, action:"viewSoldProperties"},
            // Row B - collections and receivables
            {label:"Collected", value:money(payload.collected), sub:"Paid installments", icon:ICON.wallet, action:"viewProjects"},
            {label:"Balance Due", value:money(payload.balance_due), sub:"Still outstanding", icon:ICON.money, action:"viewAgedOverdue"},
            {label:"Collection Rate", value:pct(payload.collection_pct), sub:"Collected / Sales value", icon:ICON.pct, action:"viewProjects"},
            {label:"DSO", value:`${Math.round(num(payload.dso_days))} days`, sub:"Balance / Sales x 365", icon:ICON.clock, action:"viewAgedOverdue"},
            {label:"Aged > 90 Days", value:cnt(payload.aged_overdue_units), sub:"No activity in 90+ days", icon:ICON.alert, action:"viewAgedOverdue"},
            {label:"Admin Fees", value:money(payload.admin_fees_total), sub:"Billed across all units", icon:ICON.money, action:"viewProjects"},
            // Row C - escrow compliance
            {label:"Expected Escrow", value:money(payload.required_escrow), sub:"Required allocations", icon:ICON.bank, action:"viewReconciled"},
            {label:"Allocated Escrow", value:money(payload.allocated_escrow), sub:"Funds placed in escrow", icon:ICON.bank, action:"viewUnderAllocated"},
            {label:"Escrow Shortfall", value:money(payload.escrow_shortfall), sub:"Required - Allocated", icon:ICON.alert, action:"viewOverAllocated"},
            {label:"Funded Rate", value:pct(payload.funded_pct), sub:"Allocated / Required", icon:ICON.pct, action:"viewReconciled"},
            {label:"Reconciliation Rate", value:pct(payload.recon_rate), sub:"Reconciled / Allocations", icon:ICON.check, action:"viewReconciled"},
            {label:"Missing Source", value:cnt(payload.missing_source_count), sub:"Awaiting source data", icon:ICON.alert, action:"viewAwaitingSource"},
        ];
    }

'''
s = s.replace(anchor2, helper + anchor2, 1)
print('inserted _buildCards helper')

# ---------------------------------------------------------------- 5
# Fix mojibake in the map attribution.
s = s.replace('Tiles \ufffd Esri', 'Tiles &copy; Esri')

# also ensure state.cards / aging_undated exist in useState defaults
s = s.replace("theme: \"light\", loading: true,",
              "cards: [], aging_undated: 0,\n            theme: \"light\", loading: true,")

open(p, 'w', encoding='utf-8', newline='').write(s)
print('written', len(s), 'chars')