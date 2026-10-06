# SGC -- Escrow Bridge (`sgc_escrow`)

**Property Management ↔ Accounting, joined at the escrow account.**

Version `19.0.1.0.0` · Odoo 19 · depends on `account` + `sgc_offplan_rental_property_management`

---

## 0. Current phase: accounting entries are deferred

**The module creates no accounting entries. This is enforced, not promised.**

`sgc_escrow.posting_enabled` ships **`False`**. `escrow.release.action_post()`
refuses to run until an administrator switches it on, so no journal entry can be
produced by the module -- not by an import, not by a sign-off, not by clicking
Post. Releases can still be drafted, approved, and printed as vouchers.

That means the current active work is:

| Active now | Deferred |
|---|---|
| Build the **per-unit escrow allocation register** from source facts | Creating invoice entries |
| Reconcile the register against accounting **once those entries exist** | Creating receipt entries |
| Record finance sign-off per unit | Posting escrow releases |

Loading the register creates **records on `escrow.allocation` only**. No
`account.move`, no `account.move.line`, no payments -- and the test suite asserts
this explicitly (`test_reading_the_register_creates_no_accounting_entries`).

### The reconciliation you will need later is already wired

The moment invoice and receipt entries exist, each row answers "does the
accounting agree with the allocation?" with no extra work:

| Field | Meaning |
|---|---|
| `ledger_invoiced_amount` | Posted customer invoices raised for the unit |
| `ledger_received_amount` | Payments settled against those invoices |
| `ledger_received_in_escrow` | Of those, the part that reached the project's escrow bank |
| `ledger_open_amount` | Invoiced less received |
| `reconciliation_state` | `no_source` / `no_ledger` / `matched` / `variance` |
| `reconciliation_variance` | Allocated (source) − received into escrow (ledger) |
| `reconciled`, `reconciled_on`, `reconciled_by`, `reconciliation_note` | Finance sign-off |

Every row is expected to read **`no_ledger` -- "Awaiting Accounting Entries"**
right now, because the ledger genuinely has nothing yet. That state is a
deliberate, visible "not yet comparable", never a false `matched`.

Receipts into a **non-escrow** bank do not count toward
`ledger_received_in_escrow`, so a collection that missed the escrow account shows
up as a variance rather than quietly passing.

**Sequence to follow later:** create the historic invoice entries -> create the
receipt entries into each project's escrow bank -> open
**Escrow -> Escrow Allocations** -> filter *Awaiting Accounting Entries* -> resolve
or explain each variance -> **Sign Off Reconciliation** -> then enable posting in
Settings.

---

## 1. What this module is for

Park Group sells off-plan units across four projects. Buyers deposit money into a
**project escrow account** registered with the Dubai Land Department. The DLD
allows the developer to withdraw from that account **only against certified
construction progress**. That single rule is the reason this module exists.

Until now the two halves of that problem lived in different systems:

| Half | Where it lived | What was missing |
|---|---|---|
| Projects, units, buyers, contracts, payment plans | `property.project`, `property.details`, `sale.contract` in Odoo | Nothing about escrow |
| Money | Odoo general ledger (`account.move.line`) | Nothing linking a rupee to a unit or a construction milestone |

This module is the bridge. It is a **standalone addon** -- it extends both models
by inheritance and adds three of its own. It does not modify the `account`
application, and it does not modify the property module's business logic.

---

## 2. The one non-negotiable design decision

> **The Odoo general ledger _is_ the escrow ledger. There is no parallel subledger.**

Every money figure in this module -- received, released, balance, entitlement,
releasable -- is a *query* over `account.move.line` on the project's escrow bank
account. Nothing is tallied into a shadow table that could drift.

The practical consequence: there is no escrow-to-GL reconciliation to perform,
because there is only one set of numbers. `tests/test_escrow_rollups.py` asserts
this directly by comparing the roll-up against a raw ledger search.

### Why this matters for Park Group specifically

The general ledger on `sgc_mt_parkgroup` currently holds **zero journal
entries**. The escrow register (§4) is therefore a set of *source facts* about
historic money, not a record of movements. This module keeps that distinction
explicit:

- **Allocation** (`escrow.allocation`) = what a source document says. Immutable
  provenance, snapshot values, never invented.
- **Movement** (`account.move.line`) = what actually happened in the ledger,
  going forward.

Reconciling the two is an accountant's decision, not the module's. The module's
job is to make the disagreement *visible* and priced, not to settle it.

---

## 3. Model map

```
property.project ---┬-- escrow config (bank journal, agent, retention)
   │                           │-- certified progress %  ◄-- the release basis
   │                           │
   │  ┌---┴---┐
   │  │ ledger roll-ups (computed from account.move.line) │  ◄-- NO SUBLEDGER
   │  │  received / released / balance / entitled /       │
   │  │  releasable-now                                    │
   │  └---┬---┘
   │                           │
   ├---► escrow.allocation (per unit)  ◄-- imports escrow_deferred.json
   │              required vs allocated vs variance
   │                           │
   └---► escrow.release (progress-gated withdrawal)
                       │  amount ≤ releasable_now
                       │  posted as Dr operating bank / Cr escrow bank
                       ▼
                  account.move  (escrow_release_id tags the authorised movement)
```

### Fields added

**`property.project`** -- `escrow_enabled`, `escrow_bank_journal_id`,
`escrow_release_journal_id`, `escrow_account_id` (technical), `escrow_agent_id`,
`escrow_account_ref`, `escrow_retention_pct`, `escrow_certified_progress`,
`escrow_certified_date`, `escrow_certified_by`, `escrow_progress_source`,
`escrow_progress_evidence`, plus the roll-up and register counters.

**`property.details` / `sale.contract`** -- `escrow_allocation_ids` and the
three read-only summary amounts (required / allocated / variance).

**`account.move`** -- `escrow_project_id` (stored related from
`sold_id.property_id.project_id`), `escrow_release_id`, `is_escrow_release`.

**`account.move.line`** -- `escrow_project_id`, `escrow_release_id` (stored
denormalised from the move, so escrow reporting filters the ledger without
joining through the invoice).

**`escrow.allocation`** (new) -- per-unit allocation register. See §4.

**`escrow.release`** (new) -- the withdrawal document. See §5.

---

## 4. The allocation register (`escrow.allocation`)

One row per `(project, unit)` answering: *how much of this buyer's money is
identified as sitting in escrow, and should it be?*

| Field | Meaning |
|---|---|
| `sale_price_snapshot` | Sale price **as the source document stated it** |
| `collected_amount` | Total collected per the source |
| `escrow_pct` | Escrow % required by UAE rules (e.g. `20.00` = 20%) |
| `allocated_amount` | Amount the source identifies as in escrow. **Nullable** |
| `required_amount` | `= sale_price_snapshot × escrow_pct / 100` |
| `variance_amount` | `= allocated_amount − required_amount` |
| `has_source_data` | False when the source carried no allocation figure |
| `flag_code` / `flag_note` / `reconciliation_note` | Machine-readable + human reconciliation state |

### The rule that matters most: absent stays absent

When a source document carries no escrow figure for a unit, `allocated_amount`
is left **empty**. It is not zeroed.

This is deliberate and it is the most important behaviour in the module. A zero
reconciles cleanly and looks finished. An unknown is a visible gap that finance
must close. Zeroing would manufacture false precision, and it would make the
"Allocated" total look reconciled when it is not.

`has_source_data = False` surfaces those units in the project smart button, the
project escrow statement, and a dedicated search filter, while excluding them
from the allocated total.

### Loading the deferred 2026-10-05 reconciliation

`escrow_deferred.json` (226 units) was produced by the sales reconciliation and
deliberately **not** written to the database, pending this module
(`recon_work/audit5/deferred/MANIFEST.md`).

Use **Escrow -> Import Escrow Allocations**:

- Accepts JSON or CSV.
- Columns: `project`, `unit`, `client`, `escrow_pct`, `escrow_allocated`,
  `sold`, `collected`.
- `escrow_pct` may be a fraction (`0.2586`) or a percentage (`25.86`); both are
  accepted and normalised to a percentage.
- Optional second file for reconciliation flags -- pass `flags.json` to stamp
  `BREAKDOWN_EXCEEDS_COLLECTED` and `OVERPAYMENT` rows onto the matching units.
- **Dry run by default.** Check the report, then untick and run for real.
- **Idempotent:** matched on `(project, unit)`, so a re-run refreshes source
  figures rather than duplicating rows.
- Unresolvable project/unit pairs are **reported, never guessed.**

---

## 5. The release control (`escrow.release`)

### Entitlement formula (cumulative, snapshot-based)

```
entitled_cumulative = received_total
                      × (certified_progress / 100)
                      × (1 − retention_pct / 100)

releasable_now      = max(0, entitled_cumulative − released_total)
```

Worked example: 400,000 received · 50% certified progress · 5% retention
-> entitled 190,000 · releasable 190,000. Release 150,000 -> releasable now 40,000.

### `received_total` vs `released_total` -- a distinction that protects the ceiling

- `received_total` = cumulative **inflow**: positive posted lines on the escrow
  bank account, excluding reversal entries.
- `released_total` = the net movement of posted `escrow.release` documents
  **and their reversals** -- what the authorisations have taken out of escrow
  and not yet given back (a reversed release nets back to zero).
- the project **balance** = the signed sum of **every** posted line: what the
  bank statement should show.

So a **manual** transfer out of escrow reduces the balance but does **not**
reduce `received_total` and does **not** count as an authorised release. That is
intentional: the money that was collected, and the entitlement built on it, stay
intact; only the balance tells you it left. If someone moves money out by hand,
the ceiling must not quietly drift to accommodate it.
`test_a_manual_transfer_out_is_not_counted_as_an_authorised_release` pins this.

### Snapshots

Every input -- progress, retention, received, already-released, entitled,
releasable -- is copied into the document on creation and **frozen at approval**.
An auditor reads the figures the release was authorised against, not what the
project looks like today. `Refresh Snapshots` re-baselines a draft on demand.

### Workflow

```
draft --Approve--► approved --Post Release--► posted --Reverse--► cancelled
  │                    │
  └--Cancel--► cancelled
```

- A draft may legitimately hold **zero** -- a planner can open a release before
  any money or progress exists. Positivity is enforced at approval, not at draft,
  because a release is a working document until it is committed.
- **Approve** re-checks the entitlement at the moment of approval.
- **Post** writes exactly one entry: Dr operating bank / Cr escrow bank. No P&L
  effect -- the developer's own money simply moved, exactly as the bank executes
  it.
- **Reverse** appends a reversal. A posted release is never deleted or
  cancelled, so escrow history stays append-only.
- The bank-facing **Release Voucher** restates the full entitlement arithmetic
  on one page with signature blocks for the developer and the escrow bank.

### The over-release guard

Releasing more than `releasable_now` is refused. It can only proceed with:

1. `is_override` set,
2. a non-empty `override_reason` (enforced by a SQL-time `@api.constrains`),
3. the **Escrow Manager** role,
4. the override author and reason permanently audited.

Absence of progress certification is itself a control: at 0% certified progress
the entitlement is zero, so nothing can be withdrawn until an engineer has
certified something.

---

## 6. Payment routing and the policy guard

**Routing** -- pressing *Register Payment* on a sale-contract invoice whose
project has escrow enabled pre-selects that project's escrow journal, and keeps
it selectable in the dropdown even though the account is held by an escrow agent
rather than the customer. It is only a default; the operator can still override.

**Guard** -- at post time, configurable under Settings -> Property Management ->
Escrow:

| Policy | Behaviour | Use when |
|---|---|---|
| `warn` *(default)* | Posts a chatter warning on the invoice | Day one. Zero risk of blocking finance; evidence accumulates. |
| `block` | Refuses to post | Hard DLD/RERA enforcement |
| `off` | No enforcement | Accounting runs unconstrained |

The guard **never moves money**. It reports, and optionally refuses. It only
polics unambiguous single-project inbound receipts; mixed-project batches, rent
invoices, and outbound refunds are never policed.

### What the guard is, and what it is not

Stated plainly, because it matters for how much you rely on it: this is a
**detective and speed-bump control, not a hard lock.** It identifies the escrow
project through `reconciled_invoice_ids`, which is derived from reconciliation.
A payment created with no reconciliation behind it has no invoice to attribute
to a project, so it is not policed.

That is a deliberate boundary, not an oversight. **The airtight control in this
module is the entitlement ceiling on `escrow.release`**: money cannot leave an
escrow account without an approved document whose amount is mathematically capped
by certified progress, enforced server-side, with direct writes to `state` and to
the frozen snapshots blocked. The payment policy guard makes the *collection*
side honest and surfaces exceptions early; the release ceiling is what actually
protects the account.

### Direct-write protection (the control that closes the loop)

Approving and posting both transition a release through `write()`, so the
Approver role necessarily needs write permission. On its own that permission
would also permit `write({'state': 'posted'})` -- bypassing the entitlement check
with a single RPC call.

`EscrowRelease.write()` therefore refuses direct writes to `state` and to every
frozen snapshot field, and the module's own actions write through a context flag
(`_write_controlled`) that lifts the guard only for the duration of the
workflow. Ordinary draft editing -- amount, notes, override reason -- stays open.

### Odoo 19 implementation note

`account.payment` in Odoo 19 has **no `_post()` hook** -- `action_post()` is
self-contained and flips `state` directly. The guard therefore wraps
`action_post()`, the user-facing commit point. Routing hooks
`account.payment.register._compute_journal_id` and
`_compute_available_journal_ids`.

---

## 7. Roles

| Group | Privilege |
|---|---|
| **Escrow -> User** | Read escrow registers, balances and statements; raise a draft release request (create only -- cannot move it) |
| **Escrow -> Release Approver** | Approve and post releases **within** the entitlement |
| **Escrow -> Manager** | Additionally release *above* the entitlement, with a mandatory reason |

A User may `create` a release but holds no write permission, so it cannot advance
it: both `action_approve()` and `action_post()` transition the record through
`write()`. Combined with the direct-write guard above, the Approver is the
lowest role that can move money, and only within the ceiling.

### Why the ACL looks the way it does

`ir.model.access.csv` and `ir.rule.csv` carry **no `#` comment rows**, and that
is deliberate rather than stylistic. Odoo 19's `convert_csv_import` filters only
rows whose cells are *all* empty:

```python
datas = [data_line for line in reader if any(data_line := remove_translations(line))]
```

A `#` comment row has one non-empty cell, so it survives the filter and reaches
`load()` with the 8 header column names applied to a 1-cell row -- and the install
dies with `IndexError: list index out of range`. The rationale lives here
instead:

- **`escrow.allocation`** is read-only for User and Approver. All writes --
  including re-imports and reconciliation sign-off -- are reserved to the Escrow
  Manager. It is a register of source facts, so who may change a fact is a
  deliberate, narrow decision.
- **`escrow.release`** grants Approver `write` because the approve/post actions
  need it, but *not* `unlink`: a release is never deleted, only cancelled or
  reversed.
- **User has `create` but not `write`** on `escrow.release`, so the role can
  raise a draft request and stop there.
- **Record rules** exist only for `escrow.allocation` and `escrow.release`, the
  two models this module owns. Odoo 19 removed the `groups` column from
  `ir.rule`, so rules are global; adding company rules on `account.move`,
  `account.move.line` or `sale.contract` would be redundant (they already have
  them) and would risk locking accounting out of its own ledger.

### Odoo 19 table constraints

Uniqueness is declared with `models.Constraint`, not the legacy
`_sql_constraints` list:

```python
_unique_project_unit = models.Constraint(
    "UNIQUE(project_id, unit_id)",
    "Only one escrow allocation row per unit per project.",
)
```

`_sql_constraints` is accepted and then **silently ignored** in Odoo 19 -- the
DB constraint is never created, so the register could quietly end up with two
rows for the same unit. Same convention as `account_account._check_length_prefix`.

Odoo 19 removed group-scoped `ir.rule` (no `groups` column), so record rules are
declared globally. This module adds company-isolation rules only for the two
models it owns; `account.move.line` already has eight from `account`, and
`sale.contract` has one from the property module. Redundant rules there would
only risk locking accounting out of its own ledger.

Every owned model inherits `sgc.critical.audit.mixin` per house convention, with
`_audit_watched_fields` narrowed to the financially material fields so the
verification report states exactly what is attested.

---

## 8. Documentation deliverables (QWeb PDF)

| Report | Audience | Contains |
|---|---|---|
| **Project Escrow Statement** | Escrow bank, auditor, plant | Entitlement block with the formula shown; buyer receipts per unit; releases; open reconciliation exceptions |
| **Escrow Allocation Register** | Finance, internal audit | Per-unit required vs allocated vs variance, with an explicit "source data = no" column |
| **Escrow Release Voucher** | Escrow bank, RERA | Frozen entitlement arithmetic restated in full, override disclosure, signature blocks |

---

## 9. Deliberately out of scope

1. **No escrow subledger.** The GL is the escrow ledger.
2. **No BOQ/WBS/HSE/RA billing.** Those belong to the separate construction
   suite, which is deliberately not installed.
3. **No historic per-unit journal entries.** Historic finance is a controlled
   opening-balance step for the accountant, taken against the variance figures
   this module surfaces.
4. **No unit-level release allocation.** RERA releases are per project.
5. **No multi-currency escrow splitting**, no bank-statement automation.
6. **No invented data.** Unknowns stay visibly open.

---

## 10. Deployment

Slices, in order. All rehearsed on a clone of `sgc_mt_parkgroup` first. **Only
slice A4 is active now** -- the rest are deferred until the accounting entries
exist.

| Slice | Content | Risk | Status |
|---|---|---|---|
| **A4** | Load `escrow_deferred.json` + `flags.json` into the register | Low (facts only, no postings) | **Active** |
| **A2** | Project escrow config, ledger roll-ups, move/line tagging, payment routing + guard, registers, statements | Low-medium | Built, dormant |
| **A3** | `escrow.release` workflow, override role, bank voucher | Medium (financial postings) | Built, posting gated off |
| **A5** | Create historic invoice + receipt entries, reconcile register, enable posting | High -- accountant-owned | Deferred |

Procedure per slice: branch off `prod` in `/opt/odoo/deploy/sgc-rent-mt` -> copy
this directory to `addons/sgc_escrow` -> clone DB to `sgc_mt_esctest` -> upgrade +
run tests on the clone -> verify -> prod with a fresh backup. Rollback = revert the
commit + restore the DB.

Installation is **additive and reversible**: `escrow_enabled` defaults to `False`,
posting is off, the policy defaults to `warn`, and every field defaults to today's
behaviour. Nothing changes until a project opts in.

---

## 11. Open questions for the client

These block configuration, not code. The module is fully installable without
answers, but not usable for real withdrawals.

1. **Escrow bank accounts.** Bank, IBAN/account number, escrow agent and
   registered account reference for each of the four projects (BR1, BR2, GOLF,
   RES). Without these, no escrow journal can be created and no release can be
   made.
2. **Retention policy.** Confirm 5% as the default, and whether retention
   releases at 100% certified progress.
3. **Certified progress basis.** Does the escrow bank / RERA use a **fixed
   withdrawal table** (e.g. 20% draw at 20% built), or independent engineer
   certification per milestone? The module supports both: enter the percentage
   manually with the certificate attached, or -- once construction phases land in
   the property module -- switch `escrow_progress_source` to `phases`.
3. **Oqood/SPA/RF/KYC** -- handled in Workstream B (compliance fields), not here.
4. **Historic opening balances.** Should the imported allocations become
   accounting opening entries (Dr bank / Cr receivable) summarised per project,
   or stay as contract-level facts? *Decision now taken: stay as facts. The
   allocation register is the source of truth until the accountant prepares and
   signs the entries.* The module is built so that reconciliation is a comparison,
   not a migration.
5. **R01-R14 reconciliation items.** The 17 open flags (12
   `BREAKDOWN_EXCEEDS_COLLECTED`, 2 `OVERPAYMENT`, 3 `ODOO_SOLD_REPORT_NOT`)
   need finance sign-off. The importer stamps them so they are countable, not
   buried in a spreadsheet.
6. **BNK1 usage.** Is the existing `BNK1` bank journal used for buyer receipts
   today? If so, which project does it belong to -- it can only be one project's
   escrow account, and the module enforces that exclusivity.
7. **When to enable posting.** Deliberately left off. Needs a decision once the
   historic invoice and receipt entries exist and the register has been
   reconciled against them.

---

## 12. Local verification status

Reproduce with `python tools/check_scaffold.py` from the module root.

| Check | Result |
|---|---|
| `py_compile` on all 22 Python files | pass |
| XML well-formedness on all 16 XML files | pass |
| No HTML named entities in XML (numeric references only) | pass |
| Manifest data entries resolve to real files | pass |
| No undeclared or missing data files | pass |
| Manifest `images` entries exist | pass |
| `ir.model.access.csv` / `ir.rule.csv` column shape | pass |
| Every security-referenced model is defined by this module | pass |
| Every referenced group resolves to a declared group | pass |
| Every `env.ref('sgc_escrow.*')` resolves to a declared record | pass |
| View field references against the 4 fully-owned models (76 fields) | pass |
| No removed Odoo 17+ `states=` field attribute | pass |
| Compute overrides preserve the base `@api.depends` triggers | pass |
| No stored compute depends on a non-stored field | pass |

Every rule was verified against a deliberately injected regression, so none of
them are vacuous: named entity, depend narrowing, unknown ACL model, undeclared
group, missing manifest file, wrong CSV columns, unknown view field, dangling
`env.ref`, and `states=`.

### Defects found and fixed during review

Recorded because they are the kind of thing that reaches production silently:

| Defect | Severity | Fix |
|---|---|---|
| `Release Approver` had `perm_write=0`, so it could **never** approve or post -- both action methods transition via `write()` | MAJOR | Approver now has write on `escrow.release`; a new direct-write guard preserves the boundary |
| Overriding `_compute_journal_id` / `_compute_available_journal_ids` **replaced** their base `@api.depends`, so escrow routing would go stale on company or payment-type change | MAJOR | Restated the base triggers alongside ours; regression-tested |
| With write access granted to Approvers, `write({'state': 'posted'})` would bypass the entitlement check entirely | MAJOR | `EscrowRelease.write()` blocks direct writes to `state` and every frozen snapshot |
| Roll-ups labelled with the *journal* currency while `account.move.line.balance` is in *company* currency | MAJOR | `escrow_currency_id` pinned to company currency |
| `@api.constrains` demanded `amount > 0`, so drafting a release at zero progress raised a confusing error | MINOR | Drafts may be zero; positivity enforced at approval |
| `_read_group(...)[0]` would `IndexError` on an empty result, taking the project form down | MINOR | Defensive empty-result guard |
| Manifest referenced a non-existent `static/description/banner.png` | MINOR | Removed |
| `&mdash;` / `&times;` / `&minus;` in QWeb templates are not valid XML entities (house style uses none) | MINOR | Replaced with numeric character references |
| `states={...}` (removed in Odoo 17, silently ignored) would have left the release amount permanently readonly | MAJOR | Removed; per-state control moved to the view |
| Test fixture built `account.payment.line_ids` by hand | MINOR | Fixture now uses the `account.payment.register` wizard, exercising the real flow |
| Escrow Manager test user lacked accounting groups, so posting would `AccessError` mid-flow | MINOR | Fixture grants them, mirroring a real finance user |

**Not yet run:** `odoo -u sgc_escrow --test-enable` on a staging clone of
`sgc_mt_parkgroup`. Static checks cannot catch ORM registry conflicts, xpath
resolution against live base views, or fixture assumptions about the Odoo 19
accounting flow. That is the next gate before this goes near `prod`, and it
should be run by someone with the staging clone to hand.
