# Parkgroup Real Estate — Odoo MCP server + accounting export

Connects to **pgre.odoo.com** (Odoo **18.0 Enterprise**, Odoo Online SaaS) and
exposes its accounting data over MCP, plus a one-shot bulk exporter that writes
every invoice, bill, refund, payment and journal entry to CSV/XLSX.

---

## Why this is an external MCP server (important)

Odoo Enterprise 18 does **not** have a built-in MCP endpoint. Verified against
your instance:

| Endpoint | Result on `pgre.odoo.com` |
|---|---|
| `POST /mcp` | **404** |
| `GET /mcp/sse` | **404** |
| `POST /mcp/http` | **404** |
| `POST /json/2/...` | **404** (JSON-2 is Odoo 19+) |

- Odoo's **native** MCP server arrived in **v19/v20**, not v18.
- The usual v18 workaround is an in-Odoo module (`muk_mcp`, `odoo_ai_mcp`,
  `odoo_mcp`…). **Odoo Online cannot install custom or third-party modules**,
  so that route is closed.

Therefore the only supported architecture on this tenant is a **local MCP server
that speaks the Odoo 18 external API** — JSON-RPC at `/jsonrpc`, with an
automatic XML-RPC fallback, authenticated with a normal Odoo API key. That is
what this project is.

---

## Credentials

### 1. Create a real Odoo API key

In Odoo, as the user the server should act as:

> **My Profile → Account Security → New API Key** → give it a description →
> **Generate Key** → copy it immediately (it is shown once).

⚠️ **An Odoo API key is exactly 40 characters.** If you have a longer token
(e.g. a 92-character Fernet-style string containing `#`), it is **not** an Odoo
API key and authentication will be rejected. Odoo accepts the key as the
**password** for the user's login — that is what this client does.

### 2. Configure the environment

Copy `.env.example` to `.env` and fill it in, or export the variables directly:

| Variable | Required | Meaning |
|---|---|---|
| `PGRE_URL` | no | Base URL. Default `https://pgre.odoo.com` |
| `PGRE_DB` | no | Database name. **Auto-discovered** if unset (see below) |
| `PGRE_LOGIN` | recommended | User login/email, e.g. `renbran@parkgroup.ae` |
| `PGRE_KEY` | **yes** | The 40-character Odoo API key |

> **Database-name gotcha.** On Odoo Online the database is *not* the subdomain.
> For this tenant the subdomain is `pgre` but the real database is
> **`pgre-main-23539443`** (authenticating against `pgre` fails with
> `database "pgre" does not exist`). The client auto-discovers it from
> `/web/database/list`; set `PGRE_DB` to override.

`.env` is gitignored — the key is never committed.

---

## Files

| File | Purpose |
|---|---|
| `pgre_client.py` | Transport + auth. JSON-RPC primary, XML-RPC fallback, DB auto-discovery, paging |
| `accounting.py` | Bucket definitions, Odoo domain builders, classification (pure, offline) |
| `server.py` | FastMCP server exposing 10 tools + 1 resource |
| `export_data.py` | Bulk CSV/XLSX exporter CLI |
| `selftest.py` | 78 offline assertions, no network needed |
| `mcp_smoke_test.py` | Real stdio MCP handshake; asserts tools/resources/error path |
| `README.md` | This file |

---

## Buckets — how your four categories map onto Odoo

Nothing is inferred; each bucket is a native Odoo filter.

| Bucket | Odoo source | Meaning |
|---|---|---|
| `customer_invoices` | `account.move` `move_type = out_invoice` | Customer invoices |
| `customer_refunds` | `account.move` `move_type = out_refund` | **Refunds** you owe customers |
| `vendor_bills` | `account.move` `move_type = in_invoice` | **Vendor** bills |
| `vendor_refunds` | `account.move` `move_type = in_refund` | Vendor credit notes |
| `customer_receipts` | `account.move` `move_type = out_receipt` | Sales receipts |
| `vendor_receipts` | `account.move` `move_type = in_receipt` | Purchase receipts |
| `journal_entries` | `account.move` `move_type = entry` | **Misc journal entries** |
| `customer_payments_received` | `account.payment` inbound + customer | **Customer payments** |
| `refunds_paid_to_customers` | `account.payment` outbound + customer | **Refunds paid out** |
| `vendor_payments_made` | `account.payment` outbound + supplier | **Vendor payments** |
| `refunds_received_from_vendors` | `account.payment` inbound + supplier | Refunds received |
| `internal_transfers` | `account.payment` internal | Bank ↔ cash transfers |

### The journal-entry case you asked about

`journal_entries` captures everything that is *not* an invoice, bill or payment —
accruals, reclassifications, escrow movements, manual corrections. For full GL
detail, `get_move_lines` returns flat `account.move.line` rows (account
code/name, partner, debit, credit, balance) and the exporter writes
`journal_entry_lines.csv`.

Two gotchas handled for you:

- Journal entries have **no `invoice_date`** (it is `False`), so date filtering
  them on that column silently returns zero rows. The domain builder switches to
  `date` for this bucket.
- `internal_transfers` deliberately does **not** constrain `partner_type`,
  because internal transfers have no counterparty.

---

## Running

### Bulk export (what you asked for)

```powershell
# everything, one workbook
python export_data.py --format xlsx

# CSVs as well, for a date range
python export_data.py --format both --date-from 2025-01-01 --date-to 2025-12-31

# include drafts, cap rows for a quick look
python export_data.py --format xlsx --include-draft --limit 200
```

Writes to `data/`: `odoo_financial_export.xlsx` (one sheet per dataset plus a
`_meta` sheet with db, version, transport, timestamp and row counts) and/or one
CSV per dataset.

Amounts are reported **per currency and never summed across currencies** —
the books are AED with USD property sales, so a blended total would be wrong.

### As an MCP server

```powershell
python server.py     # stdio transport
```

Register with opencode (`opencode.json`):

```json
{
  "mcp": {
    "pgre-odoo": {
      "type": "local",
      "command": ["python", "C:\\Parkgroup Data\\odoo_mcp\\server.py"],
      "enabled": true,
      "environment": {
        "PGRE_URL": "https://pgre.odoo.com",
        "PGRE_DB": "pgre-main-23539443",
        "PGRE_LOGIN": "renbran@parkgroup.ae",
        "PGRE_KEY": "<your 40-char Odoo API key>"
      }
    }
  }
}
```

### Tools

| Tool | Does |
|---|---|
| `odoo_whoami` | URL, db, uid, transport, server version, user, company |
| `list_financial_buckets` | Every bucket + how many records exist — **start here** |
| `get_invoices` | Invoices / bills / credit notes by bucket |
| `get_payments` | Payments and refunds by bucket |
| `get_journal_entries` | Misc journal entries, optionally with their lines |
| `get_move_lines` | Flat GL lines (`account.move.line`) |
| `list_journals` / `list_partners` | Reference data |
| `financial_summary` | Totals per bucket, **split by currency** |
| `find_unpaid` | Open receivables / payables for aging |

Resource: `odoo://buckets`.

---

## Migrating to a new database

### First, the honest recommendation

`pgre.odoo.com` is an **Odoo.sh** branch. If the goal is "move everything to a
new database", the **lossless** route is the platform's own backup:

1. Odoo.sh → your project → **Databases** → **Backup** → download the `.dump`.
2. Restore it into the destination: a new Odoo.sh branch, a self-hosted Odoo, or
   an Odoo Online trial database (where *Restore* appears on the database manager).

That carries over everything, including the things **no import script can
recreate**:

| Data | Survives `.dump` | Survives CSV import |
|---|---|---|
| All 7 companies, journals, chart of accounts | yes | only if mapped manually |
| Invoice ↔ payment reconciliation (`account.partial.reconcile`) | yes | **no** |
| Sequence positions (so new invoices don't collide) | yes | **no** |
| Attachments / binary fields | yes | **no** |
| Analytic distribution, multi-currency revaluation | yes | fragile |
| Fiscal-year locks, chatter, follow-ups | yes | **no** |

So use CSV only when the dump cannot express what you want — which is exactly
the case for a **clean rebuild**:

* keep only some of the 7 legal entities (Park Homes, Park Group Investment,
  Park Real Estate Dev, PBR, AIWA, Park Residency, Park I N V)
* keep only a date range (e.g. FY2025+)
* keep an audit/analysis copy outside Odoo

### `export_migration.py` — for the selective case

```powershell
# everything, dependency-ordered, with reference keys preserved
python export_migration.py --out migration_out

# just one legal entity
python export_migration.py --out migration_out --company-id 3

# a date range
python export_migration.py --out migration_out --date-from 2025-01-01 --date-to 2025-12-31

# only the datasets you need
python export_migration.py --out migration_out --only accounts partners invoices payments move_lines
```

It writes one CSV per dataset plus `manifest.json`, and differs from
`export_data.py` in three ways that matter for migration:

1. **`old_id` plus natural keys.** Accounts keep their `code`, journals their
   `code`, partners their `VAT`/`ref`. Numeric ids will not match in the target,
   so resolve references by code/VAT/name — see `REFERENCE_FIELDS`.
2. **Dependency order.** `companies → journals → accounts → taxes →
   payment_terms → partners → products → analytic → invoices/bills/refunds →
   payments → move_lines`. Parents exist before children. `manifest.json`
   records `load_order`.
3. **`bucket` and `is_refund` columns**, so the importer can tell a customer
   credit note from a vendor bill without re-deriving `move_type` logic.

Two date-column traps handled for you: journal entries and GL lines have **no
`invoice_date`** (it is `False`), so they are filtered on `date`; and the
`payments` dataset spans all five payment buckets (including internal transfers),
which a single `account.payment` domain would miss.

---

## Getting connected

Run the doctor first — it needs no credentials for the instance checks and
tells you precisely what is wrong:

```powershell
python doctor.py --info    # instance facts + endpoint support, no credentials
python doctor.py           # full auth + permissions + data-volume check
```

It reports the transport in use, your uid, which models are readable, all
companies with their currencies, and how many records each export will produce.

### Path A — API key (preferred, unattended)

Odoo → avatar → **My Profile → Account Security** → **New API Key** → Generate.
It is **exactly 40 characters**; a longer token is not an Odoo API key.

```powershell
$env:PGRE_LOGIN = "renbran@parkgroup.ae"
$env:PGRE_KEY    = "<40-character key>"
```

### Path B — reuse the browser session you are already logged into (no API key)

```powershell
# Chrome: F12 -> Application -> Storage -> Cookies -> https://pgre.odoo.com
#        -> click "session_id" -> copy Value
$env:PGRE_SESSION_ID = "<cookie value>"
python doctor.py
```

This authenticates with `POST /web/dataset/call_kw` — the same endpoint Odoo's
own web client uses — so every tool works identically.

> **Security:** the `session_id` cookie is a **full account session**. It behaves
> exactly like a password: anyone holding it is you, and it dies when you log out.
> Use Path A for anything unattended, scheduled or automated. Never commit it.

---

## Company attribution (multi-company)

`pgre.odoo.com` holds **7 legal entities**, and each project is licensed to
exactly one of them. Read from Odoo, never inferred from a name:

| Project (`building_name`) | Licensed entity | Units | Sheet |
|---|---|---|---|
| Park Residency | PARK RESIDENCY REAL ESTATE DEVELOPMENT LLC | 98 | PRY |
| PARK BEACH RESIDENCE | PARK REAL ESTATE DEVELOPMENT LLC OPC | 87 | PBR1 |
| PARK BEACH RESIDENCE II | PBR REAL ESTATE DEVELOPMENT LLC OPC | 92 | PBR2 |
| Park Golf View Residence | AIWA REAL ESTATE DEVELOPMENT LLC | 18 | PGV |
| Ajman Creek Tower 1 | PARK I N V PROPERTIES LLC | 173 | — |
| Ajman Creek Tower 2 | PARK I N V PROPERTIES LLC | 223 | — |
| GLAM RESIDENCE | PARK I N V PROPERTIES LLC | 25 | — |

Sources in priority order:

1. `product.product.company_id` — the unit's owning company (**716/716 units set**)
2. `product.template.company_id` — resolves `account.move.property_id`
3. `crm.lead.company_id` vs the worksite owner — cross-check only

**No multi-company restructure was performed.** As requested, the attribution is
recorded as an internal note: a `Company_Map` sheet, an `internal_note` column on
every reconciliation row, and a note on each Odoo-only unit.

### The invoice → unit link exists (via `property_id`, not `real_estate_ref`)

`account.move.property_id` and `account.payment.property_id` are populated on
**95.5%** of customer invoices and **94.1%** of payments. They point at
`product.template`, while the unit inventory lives in `product.product` — mixing
the two id spaces makes almost every invoice look like it references an unknown
unit, so the reconciler resolves templates by unit code before comparing.

`real_estate_ref` is empty on **all 5,376 invoices and 3,284 payments**: a
redundant second link, never populated. Pick one canonical field before
migrating.

With the link resolved, company attribution is clean: **5,136/5,136 invoices**
and **3,163/3,163 payments** are booked under the company that owns the unit.
Only **2 sheet rows** show a cross-entity document, and both are the same buyer
holding units in both PBR entities.

CRM cross-check: 397/427 leads sit under the right company. The 30 exceptions
are Ajman Creek Tower 2 / GLAM RESIDENCE leads filed under PARK HOMES
INTERNATIONAL while the project is owned by PARK I N V — a sales-ownership
question, not a licensing one.

---

## Verification

```powershell
python -m py_compile accounting.py server.py export_data.py export_migration.py `
    selftest.py pgre_client.py fieldplan.py doctor.py reconcile.py
python selftest.py              # 87/87 pass, no network
python test_field_extractor.py  # 8/8 pass
python mcp_smoke_test.py        # real MCP handshake, 10 tools, 1 resource
python validate_fields.py       # every declared field exists in the live schema
python export_data.py --help
python reconcile.py --help
```

### Sheets → Odoo reconciliation

```powershell
python reconcile.py --out reconciliation_2026-10-06.xlsx
python report_reconciliation.py   # console digest
python report_company_map.py      # company attribution digest
```

Produces an 8-sheet workbook: `Summary`, `Project_Map`, `Company_Map`,
`Reconciliation`, `Ambiguous`, `Unreconciled`, `Defects_Log`, `Clarifications`.

Three bugs this found in my own earlier logic, each a false positive:

- comparing **per-unit** sheet collections against **customer-lifetime** Odoo
  totals — now only compared when the client owns exactly one unit
- `SHOP-01/02/03` normalised to `1/2/3` and collided with real units 1,2,3 —
  shops are now namespaced as `SHOP:1`
- `property_id` (template ids) joined against `product.product` ids — produced
  4,719 phantom company mismatches; resolved via unit code, real answer is 0

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `uid=False`, `OdooAuthError` | API key rejected | Key must be **40 chars** from *My Profile → Account Security*. Not a Fernet/session token. Also confirm the login exists on *this* database. |
| `database "pgre" does not exist` | Used the subdomain | Real DB is `pgre-main-23539443`; set `PGRE_DB` or let it auto-discover |
| `HTTP 403 ... /jsonrpc is disabled` | Host disables JSON-RPC | Client automatically falls back to XML-RPC; on Odoo Online both are enabled |
| `HTTP 401/403` on a tool | Rights | The user needs Accounting read access; invoice *drafts* require extra rights |
| Empty result for journal entries | Filtered on `invoice_date` | Use the `journal_entries` bucket — it filters on `date` |
| Timeouts on large exports | Odoo Online rate limiting | Lower `--page` (e.g. 200); paging and retry/backoff are already handled |