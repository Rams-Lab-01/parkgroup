CSS = r'''

/* =====================================================================
   Executive Dashboard v2 - new layout components
   (18 KPI cards in 3 rows of 6, panels, watchlist, table, map)
   ===================================================================== */

.sgc-dash-body { display: flex; flex-direction: column; gap: 20px; }

/* ---- Sections ------------------------------------------------------ */
.sgc-section { display: flex; flex-direction: column; gap: 12px; }
.sgc-section__head { display: flex; align-items: center; justify-content: space-between; }
.sgc-section__title {
    margin: 0; font-size: 13px; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; color: var(--sgc-text-muted, #64748b);
}

/* ---- KPI grid: 6 columns, responsive down to 1 --------------------- */
.sgc-kpi-row {
    display: grid;
    grid-template-columns: repeat(6, minmax(0, 1fr));
    gap: 14px;
}
@media (max-width: 1400px) { .sgc-kpi-row { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 820px)  { .sgc-kpi-row { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 520px)  { .sgc-kpi-row { grid-template-columns: repeat(1, minmax(0, 1fr)); } }

.sgc-kpi {
    cursor: pointer;
    transition: transform .14s ease, box-shadow .14s ease, border-color .14s ease;
    min-width: 0;
}
.sgc-kpi:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 26px rgba(15, 23, 42, .14);
    border-color: var(--sgc-accent, #1e40af);
}
.sgc-kpi__value { word-break: break-word; }

/* ---- Two-column panel rows ----------------------------------------- */
.sgc-two-col {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
}
@media (max-width: 980px) { .sgc-two-col { grid-template-columns: minmax(0, 1fr); } }

.sgc-panel {
    background: var(--sgc-surface, #ffffff);
    border: 1px solid var(--sgc-border, #e2e8f0);
    border-radius: 14px;
    padding: 16px 18px;
    min-width: 0;
}
.sgc-panel__head {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 12px;
}
.sgc-panel__title {
    margin: 0; font-size: 13px; font-weight: 700;
    color: var(--sgc-text, #0f172a);
}
.sgc-panel__note {
    margin-top: 10px; font-size: 12px;
    color: var(--sgc-text-muted, #64748b);
}
.sgc-panel--map { padding: 0; overflow: hidden; }
.sgc-link-btn {
    background: none; border: 0; cursor: pointer;
    color: var(--sgc-accent, #1e40af);
    font-size: 12px; font-weight: 600; padding: 0;
}
.sgc-link-btn:hover { text-decoration: underline; }

/* ---- Charts -------------------------------------------------------- */
.sgc-chart { width: 100%; height: 280px; }
.sgc-chart--donut { height: 300px; }

/* ---- Escrow watchlist ---------------------------------------------- */
.sgc-watchlist { display: flex; flex-direction: column; gap: 2px; }
.sgc-watchlist__row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 11px 12px; border-radius: 9px; cursor: pointer;
    transition: background .14s ease;
}
.sgc-watchlist__row:hover { background: var(--sgc-hover, #f1f5f9); }
.sgc-watchlist__label { font-size: 13px; color: var(--sgc-text, #0f172a); }
.sgc-watchlist__count {
    font-size: 13px; font-weight: 700;
    color: var(--sgc-text, #0f172a);
    background: var(--sgc-chip, #eef2ff);
    border-radius: 999px; padding: 2px 10px; min-width: 34px; text-align: center;
}

/* ---- Per-project table --------------------------------------------- */
.sgc-table-wrap { overflow-x: auto; border-radius: 12px; }
.sgc-table {
    width: 100%; border-collapse: collapse; font-size: 13px;
    background: var(--sgc-surface, #ffffff);
}
.sgc-table th, .sgc-table td {
    padding: 10px 12px; text-align: left; white-space: nowrap;
    border-bottom: 1px solid var(--sgc-border, #e2e8f0);
}
.sgc-table th {
    font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
    color: var(--sgc-text-muted, #64748b); font-weight: 700;
    position: sticky; top: 0; background: var(--sgc-surface, #ffffff);
}
.sgc-table tbody tr { cursor: pointer; transition: background .14s ease; }
.sgc-table tbody tr:hover { background: var(--sgc-hover, #f1f5f9); }
.sgc-num { text-align: right !important; font-variant-numeric: tabular-nums; }
.sgc-strong { font-weight: 700; }
.sgc-neg { color: #dc2626; font-weight: 700; }

/* ---- Map ----------------------------------------------------------- */
.sgc-map { width: 100%; height: 420px; }
@media (max-width: 640px) { .sgc-map { height: 320px; } }
.sgc-leaflet-pin { background: none; border: 0; }
.sgc-pin-core, .sgc-pin-halo, .sgc-pin-pulse {
    position: absolute; border-radius: 50%;
}
.sgc-pin-core {
    width: 12px; height: 12px; left: 8px; top: 8px;
    border: 2px solid #fff; box-shadow: 0 1px 4px rgba(0,0,0,.35);
}
.sgc-pin-halo {
    width: 22px; height: 22px; left: 3px; top: 3px; opacity: .25;
}
.sgc-pin-pulse {
    width: 28px; height: 28px; left: 0; top: 0; opacity: .16;
}
.sgc-popup__city { font-weight: 700; font-size: 13px; }
.sgc-popup__count { font-size: 12px; color: #64748b; }

/* ---- Loading ------------------------------------------------------- */
.sgc-loading {
    display: flex; align-items: center; justify-content: center; gap: 12px;
    padding: 70px 0; font-size: 14px; color: var(--sgc-text-muted, #64748b);
}
.sgc-spinner {
    width: 20px; height: 20px; border-radius: 50%;
    border: 2px solid var(--sgc-border, #e2e8f0);
    border-top-color: var(--sgc-accent, #1e40af);
    animation: sgc-spin .8s linear infinite;
}
@keyframes sgc-spin { to { transform: rotate(360deg); } }
'''

p = 'rental_property_dashboard.css'
s = open(p, encoding='utf-8', errors='replace').read()
if '.sgc-two-col' not in s:
    s = s.rstrip() + '\n' + CSS
    open(p, 'w', encoding='utf-8', newline='').write(s)
    print('appended v2 component styles')
else:
    print('already present - skipped')
print('total length', len(open(p, encoding='utf-8', errors='replace').read()))