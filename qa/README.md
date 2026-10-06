# QA / regression kit

| File | What it checks | How to run |
|---|---|---|
| `dashboard_harness/` | Property dashboard in a real browser (Chromium via Playwright) with a stubbed Odoo: 18 KPI cards, 5 charts, map, clicks, theme | copy `components/rental_property_dashboard.js` -> `comp.js`, `xml/template.xml` -> `template.xml`, copy `echarts.min.js`, `leaflet.js`, `leaflet.css`, `style.css`, `dash.css` next to `index.html`, serve with `python3 -m http.server 8765`, then `node run.cjs` |
| `portal_stress.py` | Broker portal: 120-registration load, same-email race, 200-guess brute force, fuzz/XSS/null bytes/huge input, large and hostile uploads | see docstring |
| `rpc_concurrency.py` | Double clear of one cheque, duplicate cheque numbers, parallel creation, double approval | see docstring |
| `orm_bulk.py` | 5000 cheques, 300 brokers: timings, memory, cron idempotency | `odoo shell < orm_bulk.py` |

Module test suites: `odoo -d <db> -i sgc_pdc_management,sgc_broker_registration --test-tags /sgc_pdc_management,/sgc_broker_registration --stop-after-init`.

Run Odoo with `--workers 4` (not threaded) for the HTTP tests and keep the stress database separate from production:
the scripts create data.
