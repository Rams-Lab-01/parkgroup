# Park Group — Dashboard KPI Replacement Plan (v2, executable)

**Status:** final. Supersedes v1 (`c4e987d`). Prepared 2026-10-06 against
`sgc_mt_parkgroup` @ `sgc_offplan_rental_property_management` `19.0.2.73`
(repo HEAD `e7460cc`, branch `prod`, working tree clean).

**Hard constraints (from the owner):**
1. **Only `sgc_mt_parkgroup` is modified.** No upgrade, no SQL, no data change on
   `sgc_mt_template` (the DB client tenants are cloned from — currently
   `datistemplate=true, datallowconn=false`; left closed) nor on `esctest`/`rectest`.
2. **Zero hardcoded or placeholder data.** Every value on every card, chart,
   marker and table cell is aggregated live from real records (SQL/ORM pivots
   over `property.details`, `sale.contract`, `sale.contract.installment`,
   `escrow.allocation`, `property.project`). No fabricated series, no sine
   "estimates", no invented map pins.
3. **Everything clickable.** Each KPI card opens the underlying record list with
   an exact domain; each chart series and each escrow-watchlist row does the same.

---

## 0. Critique of v1 — what was right, what was wrong

Verified against the live DB and `Consolidated_Sales_Workbook (4).xlsx` on
2026-10-06. Evidence in §5.

| # | v1 claim | Verdict | Corrected position |
|---|---|---|---|
| 1 | Rental KPIs (7 cards) are structurally dead for an off-plan developer | **RIGHT** — keep removal | Confirmed: zero rented/booked/maintenance rows, no landlords, rent.bill empty. |
| 2 | Escrow is the differentiator; 160/54/10/2 classification | **RIGHT** | Reproduced from DB *exactly*: reconciled 160, no-source 54, under 10, over 2 (`has_source_data` + `variance_amount`). |
| 3 | KPIs 9–13 (collections) computable from installments; "one piece I could not confirm" | **PARTLY WRONG** | Resolved: `sale.contract.installment` carries `state`, `amount`, `payment_date`, `due_date` — but **`due_date` is populated only on 235/555 paid rows and 0/226 pending rows**. "Overdue by due date" is **not** computable. See §3B for the DB-native aging that replaces it. |
| 4 | KPI 19–20 Delivery (handover) | **WRONG — infeasible** | `sale.contract.handover_date` is **empty on 100% (0/228) of contracts**. Delivery section deleted. Construction progress also dead (`project_milestone` = 0 rows). |
| 5 | Admin Fees / Commission / Construction "defer until confirmed" | **RIGHT** | Commission lines = 0 rows (`commission_line`, `property_commission_line`); milestones = 0 rows. Admin Fees **is** real → promoted into v2 (§3B item 12; Σ = AED 618,463.97, exact workbook match). |
| 6 | Map: Option A (project pins) vs B (region rollup); asked owner for coordinates | **HALF-WRONG** | `region_id` is **empty on all 4 projects** — option B impossible as written. But `city` + `address` are real (Al Marjan Island RAK ×2, Al Zorah Ajman, Warsan 4 Dubai). v2 ships **Option A**: two nullable fields + real coordinates for the 4 developments, stored **in parkgroup only**. |
| 7 | "Do not delete moves 96/97/98" | **RIGHT** | No journal data touched at all in v2. |
| 8 | Charts 3–4 retargeted, keep type+state charts | **INSUFFICIENT** | The "Revenue Performance" chart is a **fabricated sine wave** (`wave()` in JS) — the single worst placeholder on the page. v2 replaces it with the real monthly collections timeline (from `installment.payment_date`). |
| 9 | Open question: "Should letting cards move to a secondary Leasing section?" | **RESOLVED — no** | Park Group has zero rent records; a Leasing section would be an empty shelf. Delete entirely. |
| 10 | Missing from v1 | — | (a) the no-placeholder rule applied to *every* widget; (b) drill-down requirement; (c) template-DB isolation; (d) exact workbook reconciliation table; (e) deploy ritual (asset purge) — all added in v2. |

---

## 1. What the dashboard shows today vs v2

Today (14 cards): Total Properties · Available · Sales Revenue · Rental Income ·
Pending Invoices · Customers · Landlords · Projects · Sub-Projects · Regions ·
Booked · Sold · Rented · Maintenance — 7 of which are structurally always zero
for an off-plan developer — plus a fabricated revenue chart and 8 invented map
pins (Marina Heights, JVC Residences, …), none of which are Park Group assets.

v2 (18 cards, 3 rows of 6 + watchlist + 4 charts + per-project table + real map)
— every card is a decision the developer actually makes: inventory sold,
money collected, money outstanding, escrow compliance.

---

## 2. Reference: exact workbook reconciliation targets

Source: `Consolidated_Sales_Workbook (4).xlsx` (Project Dashboard / Escrow
Allocation Summary sheets), cross-checked live. All figures below were
**reproduced from the DB** during recon (differences ≤ AED 0.10 rounding):

| KPI | Workbook | DB formula |
|---|---|---|
| Total Units | 298 | `count(property.details)` |
| Sold / Available | 228 / 70 | `state in (sold, available)` |
| Sell-through % | 76.51% | sold ÷ total |
| Sales Value | 288,412,074.97 | `Σ sale_contract.sale_price` |
| Collected | 111,215,777.90 | `Σ total_paid` (= Σ paid installments) |
| Balance Due | 177,196,297.20 | net `Σ(sale_price − total_paid)` (incl. 2 over-collected credits of −507,819) |
| Collection % | 38.56% | collected ÷ sales value |
| DSO days | 224.25 | `balance ÷ sales value × 365` |
| Avg PSF (sold) | 1,884.71 | `Σ sale_price ÷ Σ area` (sold) → 1,884.70 |
| Admin fees | 618,463.97 | `Σ admin_fee` → exact |
| Expected escrow | 61,757,867.62 | `Σ escrow.allocation.required_amount` |
| Allocated escrow | 60,149,563.30 | `Σ allocated_amount` |
| Shortfall | −1,608,304.32 | allocated − required (matches workbook; note: per-row `variance_amount` sums to −790,704 because 54 rows have no source figure — the card uses the workbook definition) |
| Class: reconciled / under / over / no-source | 160 / 10 / 2 / 54 | `has_source_data` + `|variance|` classification → exact |
| Funded % (per project) | 96.5 / 98.6 / 89.8 | allocated ÷ required → exact |
| Reconciliation rate (per project) | 74.7 / 93.3 / 24.0 | reconciled ÷ sold → exact |

**Documented divergence (1):** workbook "Overdue Units 214 / AED 163.5M" and
its aging buckets are **not reproducible** from the DB — they were computed
offline from source spreadsheets that carried payment dates the DB import never
received (93/228 contracts have zero dated payments; pending rows have no due
dates at all). v2 therefore defines **"Aged > 90 days"** from DB-real data:
`balance_due > 0` AND `last_activity_date < today − 90`, with last activity =
most recent recorded payment, else contract date. The card's drill-down lists
exactly the units it counts, so the number is always auditable on screen.

**Documented divergence (2):** workbook "Avg Unit Size 513.51" is a formula
quirk (sold area ÷ 298). v2 shows `avg(area)` over all units (735.08) with the
sold-only average (671.18) in the tooltip — both defensible, both real.

---

## 3. Final KPI specification (v2)

### A. Inventory & sales (row 1)
| # | Card | Value (live) | Drill-down (domain) |
|---|---|---|---|
| 1 | Total Units | 298 | `property.details` all |
| 2 | Sold Units | 228 | `property.details [state=sold]` |
| 3 | Available Units | 70 | `property.details [state=available]` |
| 4 | Sell-Through % | 76.5% | `property.details [state=sold]` |
| 5 | Sales Value (sold) | AED 288.41M | `sale.contract [state=signed]` |
| 6 | Avg PSF (sold) | 1,884.70 | `property.details [state=sold]` |

### B. Collections (row 2)
| # | Card | Value | Drill-down |
|---|---|---|---|
| 7 | Collected | AED 111.22M | `sale.contract.installment [state=paid]` |
| 8 | Balance Due | AED 177.20M | `sale.contract [balance_due>0.01]` |
| 9 | Collection % | 38.6% | `sale.contract.installment [state=paid]` |
| 10 | DSO (days) | 224 | `sale.contract [balance_due>0.01]` |
| 11 | Aged > 90 days | units (+AED in sub) | `sale.contract [balance_due>0.01, last_activity_date <= today−90]` |
| 12 | Admin Fees | AED 618,463.97 | `property.details [admin_fee>0]` |

### C. Escrow compliance (row 3)
| # | Card | Value | Drill-down |
|---|---|---|---|
| 13 | Expected Escrow | AED 61.76M | `escrow.allocation` all |
| 14 | Allocated Escrow | AED 60.15M | `escrow.allocation` all |
| 15 | Escrow Shortfall | −AED 1.61M | `escrow.allocation [has_source_data=true, variance_amount<0]` |
| 16 | Escrow Funded % | 97.4% | `escrow.allocation` all |
| 17 | Reconciliation Rate | 70.2% | `escrow.allocation [has_source_data=true, |variance|≤0.01]` → list |
| 18 | Missing Escrow Source | 54 | `escrow.allocation [has_source_data=false]` |

### Watchlist panel (replaces "Contract Status" alerts)
Four clickable rows: Reconciled 160 · Under-allocated 10 · Over-allocated 2 ·
Awaiting source 54 — each → `escrow.allocation` filtered as above.

### Charts (all live aggregates)
1. **Unit Mix** donut — `unit_type` distribution (studio 142 / 1br 132 / 2br 19 / 3br 2 / n-a 3).
2. **Sell-Through by Project** stacked bars — sold vs available per project.
3. **Collections Received** monthly bars — `Σ installment.amount` grouped by
   `payment_date` month (real timeline; replaces the fabricated sine wave).
4. **Escrow Compliance by Project** grouped bars — required vs allocated.
5. **Receivables Aging** bars — 5 DB-native buckets (0–30/31–60/61–90/91–180/180+).

### Per-project table (replaces the status strip; workbook's best artifact)
Project · Units · Sold · Sell-% · Sales Value · Collected · Expected Escrow ·
Allocated · Variance · Recon rate · Funded %. Row click → units of that project.

### Map (kept, now truthful)
Real pins from `property.project.geo_latitude/longitude` (added, populated for
the 4 real developments on parkgroup only):
- PARK Beach Residence I / II — Al Marjan Island, Ras Al Khaimah
- PARK Golf Views — Al Zorah, Ajman
- PARK Residency — Warsan 4, Dubai
Popup shows real counts + city; click opens the project record. No pin renders
if coordinates are empty (graceful for other tenants).

---

## 4. Implementation & deploy

### Code (shared module `sgc_offplan_rental_property_management`, v19.0.2.73 → 19.0.2.74)
| File | Change |
|---|---|
| `models/core/property_details.py` | **add** `get_development_kpis()` (new); `get_property_stats()` untouched |
| `models/core/property_project.py` | **add** `geo_latitude`, `geo_longitude` (nullable floats) |
| `models/core/sale_contract.py` | **add** stored computed `balance_due`, `collection_pct`, `last_activity_date` (domain-filterable for drill-downs) |
| `static/src/components/rental_property_dashboard.js` | rewrite data load, charts, map, drill-down actions |
| `static/src/xml/template.xml` | new card rows, watchlist, table, map block |
| `static/src/components/rental_property_dashboard.css` | 6-col KPI grid, table + watchlist styles |
| `views/core/sale_contract_views.xml` | add the 3 new fields to the contract list view |

### Data (parkgroup only, via Odoo shell — ORM writes)
- Set `geo_latitude/longitude` on projects 139/140/141/142.

### Deploy ritual (per HANDOVER §12.4 + carry-forward rules)
1. Backup: `pg_dump -Fc sgc_mt_parkgroup → /opt/odoo/backups/sgc_rent_mt/manual_20261006_dashboard-kpis/` + TOC validation.
2. `docker exec sgc_rent_mt odoo -d sgc_mt_parkgroup -u sgc_offplan_rental_property_management --stop-after-init --no-http` — **parkgroup only**.
3. Purge assets: `DELETE FROM ir_attachment WHERE name LIKE 'web.assets_web.%' AND url IS NOT NULL;` (on parkgroup only), fetch bundle over HTTP to rebuild.
4. Restart container only if `.py` registry needs it (upgrade handles it).
5. Commit on `prod` with a named ref; **no push, no template touch**.

### Verification matrix (must all pass)
- All §2 workbook KPIs render, to the cent (except documented divergences).
- Every card/list drill-down opens the matching records (spot-check counts).
- Map renders exactly 4 real projects; zero invented names in JS.
- `grep` the new JS for fabricated math (`wave`, hardcoded pin arrays) → empty.
- Dashboard loads in light+dark, no console errors (`client action registered` ×1).
- Template DB untouched: `datistemplate=t, datallowconn=f`, no new module version.

---

## 5. Evidence log (recon, 2026-10-06)

- DB: 228 contracts `signed`; installments 555 paid (AED 111,215,778) / 226 pending (AED 177,704,116); 0 overdue-by-due-date (no pending due dates); escrow 226 rows → required 61,757,867.62 / allocated 60,149,563.30; classification 160/10/2/54 exact.
- `handover_date` 0/228; `commission_line` 0; `project_milestone` 0; `rent.bill` unused; `region_id` empty on all projects; cities/addresses real.
- Workbook reproduced for: units/sold, sell-through, sales value, collected, balance, DSO, PSF, admin fees, all escrow figures, funded %, recon rates.
- Files reviewed: dashboard JS/XML/CSS, `property_details.py`, `sale_contract.py` (+views), `property_project.py`, escrow allocation model/views, manifest, HANDOVER §12.4.
