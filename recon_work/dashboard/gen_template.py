TPL = '''<?xml version="1.0" encoding="UTF-8"?>
<templates xml:space="preserve">

    <t t-name="sgc_offplan_rental_property_management.RentalPropertyDashboard" owl="1">
        <div class="sgc-re-dashboard">

            <!-- ============================= HEADER ============================= -->
            <header class="sgc-header">
                <div class="sgc-header__brand">
                    <div class="sgc-header__brand-icon">
                        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M3 21V9l9-6 9 6v12"/><path d="M9 21v-7h6v7"/>
                        </svg>
                    </div>
                    <div class="sgc-header__brand-text">
                        <div class="sgc-header__brand-name"><t t-esc="state.company_name"/></div>
                        <div class="sgc-header__brand-sub">Executive Dashboard</div>
                    </div>
                </div>
                <div class="sgc-header__actions">
                    <button class="sgc-icon-btn sgc-theme-toggle" t-on-click="toggleTheme" title="Toggle theme">
                        <svg class="sgc-theme-toggle__icon sgc-theme-toggle__icon--sun" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>
                        </svg>
                        <svg class="sgc-theme-toggle__icon sgc-theme-toggle__icon--moon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
                        </svg>
                    </button>
                </div>
            </header>

            <!-- ============================= MAIN ============================= -->
            <main class="sgc-main">

                <div class="sgc-loading" t-if="state.loading">
                    <div class="sgc-spinner"/>
                    <span>Loading dashboard data...</span>
                </div>

                <div class="sgc-dash-body" t-if="!state.loading">

                    <!-- ===================== ROW A - INVENTORY &amp; SALES ===================== -->
                    <section class="sgc-section">
                        <div class="sgc-section__head">
                            <h2 class="sgc-section__title">Inventory &amp; Sales</h2>
                        </div>
                        <div class="sgc-kpi-row">
                            <div class="sgc-kpi" t-foreach="state.cards.slice(0,6)" t-as="card" t-key="card_index"
                                 t-on-click="this[card.action]()">
                                <div class="sgc-kpi__header">
                                    <div class="sgc-kpi__label"><t t-esc="card.label"/></div>
                                    <div class="sgc-kpi__icon" t-raw="card.icon"/>
                                </div>
                                <div class="sgc-kpi__value"><t t-esc="card.value"/></div>
                                <div class="sgc-kpi__sub"><t t-esc="card.sub"/></div>
                            </div>
                        </div>
                    </section>

                    <!-- ===================== ROW B - COLLECTIONS ===================== -->
                    <section class="sgc-section">
                        <div class="sgc-section__head">
                            <h2 class="sgc-section__title">Collections &amp; Receivables</h2>
                        </div>
                        <div class="sgc-kpi-row">
                            <div class="sgc-kpi" t-foreach="state.cards.slice(6,12)" t-as="card" t-key="card_index"
                                 t-on-click="this[card.action]()">
                                <div class="sgc-kpi__header">
                                    <div class="sgc-kpi__label"><t t-esc="card.label"/></div>
                                    <div class="sgc-kpi__icon" t-raw="card.icon"/>
                                </div>
                                <div class="sgc-kpi__value"><t t-esc="card.value"/></div>
                                <div class="sgc-kpi__sub"><t t-esc="card.sub"/></div>
                            </div>
                        </div>
                    </section>

                    <!-- ===================== ROW C - ESCROW ===================== -->
                    <section class="sgc-section">
                        <div class="sgc-section__head">
                            <h2 class="sgc-section__title">Escrow Compliance</h2>
                        </div>
                        <div class="sgc-kpi-row">
                            <div class="sgc-kpi" t-foreach="state.cards.slice(12,18)" t-as="card" t-key="card_index"
                                 t-on-click="this[card.action]()">
                                <div class="sgc-kpi__header">
                                    <div class="sgc-kpi__label"><t t-esc="card.label"/></div>
                                    <div class="sgc-kpi__icon" t-raw="card.icon"/>
                                </div>
                                <div class="sgc-kpi__value"><t t-esc="card.value"/></div>
                                <div class="sgc-kpi__sub"><t t-esc="card.sub"/></div>
                            </div>
                        </div>
                    </section>

                    <!-- ===================== HERO - UNIT MIX + WATCHLIST ===================== -->
                    <section class="sgc-two-col">
                        <div class="sgc-panel">
                            <div class="sgc-panel__head">
                                <h3 class="sgc-panel__title">Unit Mix</h3>
                                <button class="sgc-link-btn" t-on-click="viewAllProperties">View units</button>
                            </div>
                            <div class="sgc-chart sgc-chart--donut" t-ref="unitMixChart"/>
                        </div>
                        <div class="sgc-panel">
                            <div class="sgc-panel__head">
                                <h3 class="sgc-panel__title">Escrow Watchlist</h3>
                            </div>
                            <div class="sgc-watchlist">
                                <div class="sgc-watchlist__row" t-foreach="state.watchlist" t-as="wl" t-key="wl.label"
                                     t-on-click="open('escrow.allocation', wl.label, wl.domain)">
                                    <span class="sgc-watchlist__label"><t t-esc="wl.label"/></span>
                                    <span class="sgc-watchlist__count"><t t-esc="wl.count"/></span>
                                </div>
                            </div>
                        </div>
                    </section>

                    <!-- ===================== CHARTS ===================== -->
                    <section class="sgc-two-col">
                        <div class="sgc-panel">
                            <div class="sgc-panel__head">
                                <h3 class="sgc-panel__title">Sell-Through by Project</h3>
                            </div>
                            <div class="sgc-chart" t-ref="sellThroughChart"/>
                        </div>
                        <div class="sgc-panel">
                            <div class="sgc-panel__head">
                                <h3 class="sgc-panel__title">Monthly Collections</h3>
                            </div>
                            <div class="sgc-chart" t-ref="collectionsChart"/>
                        </div>
                    </section>

                    <section class="sgc-two-col">
                        <div class="sgc-panel">
                            <div class="sgc-panel__head">
                                <h3 class="sgc-panel__title">Escrow: Required vs Allocated</h3>
                            </div>
                            <div class="sgc-chart" t-ref="escrowChart"/>
                        </div>
                        <div class="sgc-panel">
                            <div class="sgc-panel__head">
                                <h3 class="sgc-panel__title">Receivables Aging</h3>
                            </div>
                            <div class="sgc-chart" t-ref="agingChart"/>
                            <div class="sgc-panel__note" t-if="state.aging_undated">
                                <t t-esc="formatCurrency(state.aging_undated)"/> has no activity date on record and cannot be aged.
                            </div>
                        </div>
                    </section>

                    <!-- ===================== PER-PROJECT TABLE ===================== -->
                    <section class="sgc-section">
                        <div class="sgc-section__head">
                            <h2 class="sgc-section__title">Performance by Project</h2>
                        </div>
                        <div class="sgc-table-wrap">
                            <table class="sgc-table">
                                <thead>
                                    <tr>
                                        <th>Project</th>
                                        <th class="sgc-num">Units</th>
                                        <th class="sgc-num">Sold</th>
                                        <th class="sgc-num">Available</th>
                                        <th class="sgc-num">Sell %</th>
                                        <th class="sgc-num">Sales Value</th>
                                        <th class="sgc-num">Collected</th>
                                        <th class="sgc-num">Required Escrow</th>
                                        <th class="sgc-num">Allocated</th>
                                        <th class="sgc-num">Shortfall</th>
                                        <th class="sgc-num">Recon %</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <tr t-foreach="state.project_rows" t-as="row" t-key="row.code"
                                        t-on-click="viewProjects()">
                                        <td class="sgc-strong"><t t-esc="row.code"/></td>
                                        <td class="sgc-num"><t t-esc="row.units"/></td>
                                        <td class="sgc-num"><t t-esc="row.sold"/></td>
                                        <td class="sgc-num"><t t-esc="row.available"/></td>
                                        <td class="sgc-num"><t t-esc="formatPct(row.sell_pct)"/></td>
                                        <td class="sgc-num"><t t-esc="formatCurrency(row.sales_value)"/></td>
                                        <td class="sgc-num"><t t-esc="formatCurrency(row.collected)"/></td>
                                        <td class="sgc-num"><t t-esc="formatCurrency(row.required_escrow)"/></td>
                                        <td class="sgc-num"><t t-esc="formatCurrency(row.allocated_escrow)"/></td>
                                        <td class="sgc-num" t-att-class="row.variance &gt; 0.01 ? 'sgc-num sgc-neg' : 'sgc-num'">
                                            <t t-esc="formatCurrency(row.variance)"/>
                                        </td>
                                        <td class="sgc-num"><t t-esc="formatPct(row.recon_rate)"/></td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                    </section>

                    <!-- ===================== MAP ===================== -->
                    <section class="sgc-section">
                        <div class="sgc-section__head">
                            <h2 class="sgc-section__title">Development Locations</h2>
                        </div>
                        <div class="sgc-panel sgc-panel--map">
                            <div class="sgc-map" t-ref="map"/>
                        </div>
                    </section>

                </div>
            </main>
        </div>
    </t>
</templates>
'''

open('template.xml', 'w', encoding='utf-8', newline='').write(TPL)
print('template.xml written,', len(TPL), 'chars')

import xml.dom.minidom
xml.dom.minidom.parse('template.xml')
print('XML well-formed OK')