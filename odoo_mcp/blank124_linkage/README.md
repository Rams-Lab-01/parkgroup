# blank124 — cross-check of the 124 blanked payment attributions

Audit trail for the payment-attribution repair performed on the Parkgroup
production instance (`sgc_mt_parkgroup`, Odoo 19) on 2026-10-21/22.

Context: a one-off maintenance blanked 124 legacy `account.payment` rows whose
unit attribution could not be corroborated from inside the target database
(217 other rows were re-confirmed and left untouched). This folder holds the
evidence used to recover those 124 attributions from the **source** system and
the artifacts produced when the recovered attributions were written to
production.

## Source of truth

`pgre.odoo.com` (Odoo.sh, Odoo 18) — the pre-migration system the production
data was migrated from. Accessed **read-only** through `odoo_mcp/pgre_client.py`
(credentials in `odoo_mcp/.env`, never committed). The pre-migration export in
`odoo_mcp/migration_out/` was used for bulk matching.

Two decisive facts in pgre made the recovery possible:

* `account.payment.property_id` — the old system stored the unit **per
  receipt** (the unit was a `product.template`).
* `crm.lead.property_id` — old CRM opportunities carry the unit they refer to
  (leads were named after the unit number, e.g. lead `309`).

## Method

1. Match each of the 124 target payments to its pgre counterpart by
   `(partner, amount, date)`; read the unit pgre recorded on that receipt.
2. Cross-check with pgre CRM leads and pgre invoices (`property_id` + the
   `OC/...` contract reference).
3. Where pgre had no receipt row, fall back to the partner's pgre history and
   CRM leads, and match on amount + day against *all* pgre partners (this is how
   the Al Fatlawi rows turned out to belong to a different customer).
4. Only rows where pgre agreed on the unit were restored; everything else was
   reported for a decision.

**Result: 124/124 rows resolved**, and for 112 of them the pgre unit agreed
with the unit the payment had carried before the blank (zero disagreements).
The remaining 12 were the Al Fatlawi rows, which pgre showed belong to
*Ian Richard Watson & Gurmuke John Singh* on unit 309 (PBR II) — the payment
was correctly attributed to the unit, but booked on the wrong customer.

## What was written to production

| Step | Effect |
|---|---|
| Re-apply | 124 payments restored to their pre-blank `(property_id, project_id, property_unit_no)`, values taken from the pre-maintenance backup and validated row-by-row against pgre |
| Durability | those rows have no live reconciliation, so a stored compute would wipe them; they were converted to **manual unit links** (`sgc_unit_link`), which the module only allows when no settled invoice carries a unit |
| Hardening | 216 further attributed payments with no reconciliation behind them were pinned the same way (the only genuinely fragile rows: every other attributed payment is derive-backed) |
| Customer fix | 12 unit-309 receipts re-pointed to partner 847, which owns their `OC/2026/0184` instalment invoices (848 keeps Fatlawi's own 57 receipts on units 307/310) |
| Conflicts | 5 payments whose stored unit disagreed with the unit of the invoice they settle were resolved with pgre + finance: Andrii → 608 @ PBR I, Raphael → 509 @ PBR II, Halil → 302 and 502 @ PBR II, Plamen → 412 @ Park Residency |

Final production state: 3377 payments · 3129 attributed · 344 manual links ·
0 attribution conflicts.

## Artifacts

* `final_rows.csv` / `final_rows.json` — per-row resolution of the 124 with the
  evidence class and the pgre CRM context.
* `linkage.json` — the raw payment-to-pgre linkage (exact / loose matches).
* `crm_leads.json`, `crm_units.json` — pgre CRM leads and the units they point at.
* `report_v1.json` — per-row partner-level unit consensus.
* `vendor_plan.csv` — the vendor breakdown of the 124 with the unit each vendor resolves to.
* `relink_expected.csv` — the (pid → unit, project, evidence) expectation set used to gate the production write.
* `relink_final_124.csv` — the same set with the pgre evidence attached.
* `pgre_relink_124.csv` / `.json` — the 124-row plan with per-row evidence.
* `prod_artifacts/` — the artifacts produced on the VPS:
  * `payunit_blank124_relink_applied_20261022.csv` — the 124 rows with what was applied
  * `payunit_blank124_relink_expected_20261022.csv` — the verification set
  * `relink_values_20261022.csv` — the exact `(pid, property_id, project_id, property_unit_no)` written
  * `manual_link_candidates_20261022.csv` — the 216 hardened rows
  * `attribution_conflicts_before_fix_20261022.csv` / `..._after_fix_20261022.csv` — the 5 conflicts and the empty result
  * `payunit_blank124_vendor_breakdown_20261021.csv`, `payunit_blank124_payment_list_20261021.csv`, `payunit_maintenance_audit_20261021.csv`

## Scripts

`scripts/` holds the analysis, in the order it was run:
`pgre_probe_01…09` (auth, matching, CRM, final resolution),
`pgre_partner_identity.py` / `split_partner_848_payments.py` (the 848/847
customer split), `probe_fatlawi_*.py` / `mine_fatlawi_accounts.py` (the
Al Fatlawi investigation), `conflict_pgre_01…06` (the five conflicts),
`build_relink_expectations.py`, `export_relink_artifacts.py`,
`report_vendor_summary.py`.

They read credentials from `odoo_mcp/.env` (`PGRE_URL`, `PGRE_DB`,
`PGRE_LOGIN`, `PGRE_KEY`) and the bulk export in `odoo_mcp/migration_out/`.

## Caveats for the reviewer

* pgre was only ever read — no write reached the source system.
* The production writes were done as Odoo ORM operations (a throwaway module
  with a `post_init_hook`, since `odoo shell` does not execute piped stdin in
  this build); the module was removed afterwards and the registry reloaded.
* Posted journal entries keep their original partner label — the 12 receipts
  re-pointed to 847 still show their booked counterparty on the entry itself.
* `sgc_mt_parkgroup_clone` (a stale pre-`unit_link` copy of production) is
  still present in the production postgres container; it is not used by the
  runtime and can be dropped.
