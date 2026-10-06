# UAE-Standard Report Audit — `sgc_offplan_rental_property_management`

Scope: Phase 4 of `.omc/plans/property-management-e2e-unification-plan.md`. Reference checklist
is general UAE real-estate practice (RERA/DLD/Ejari/AMC conventions), **not legal certification**.

Note: the module actually ships **6** existing report templates, not 5 as originally scoped
(`sales_offer_template.xml` for `property.vendor` and `sales_offer_property_template.xml` for
`property.details` are two distinct "Sales Offer" variants). This audit covers all 6, plus the 2
new reports added below — **8 report templates total**.

## Legend
✅ present and rendered · ⚠️ field exists on model but wasn't rendered (fixed in this pass, see
"Fixes applied") · ❌ no backing model field anywhere in the module (schema gap, not just a
template gap) — flagged, not fixed, since adding it is a modelling decision beyond report scope.

---

## 1. Off-plan (SPA + Oqood) — `sales_offer_template.xml`, `sales_offer_property_template.xml`, `sales_purchase_agreement_template.xml`

| Field | Status | Notes |
|---|---|---|
| Buyer/seller names | ✅ | `customer_id`/`vendor_id`/`owner_id` |
| Buyer/seller ID or passport number | ❌ | No ID/passport field anywhere on `res.partner` in this module |
| Broker + agency name | ✅ | `broker_id` |
| Broker/agency RERA or BRN number | ❌ | No RERA/BRN field on `res.partner` |
| Project name | ✅ | `property_id.project_id.name` |
| Master developer | ❌ | `property.project` has no developer field |
| Plot/land number | ❌ | No field on `property.details` |
| DLD project M-code | ❌ | No field anywhere |
| RERA project registration status | ❌ | No field anywhere |
| Unit number / floor / building | ❌ | Only `name` (free text) exists; no structured unit/floor/building fields |
| Size / type / parking | ⚠️/❌ | Size (`area`) ✅, type (`property_type`) ✅, parking ❌ (no field) |
| Total price AED | ✅ | `sale_price`, always AED-prefixed |
| DLD 4% registration fee | ⚠️→✅ | `dld_fee`/`dld_fee_percentage` **exist on `property.details` but were never rendered** — added to `sales_purchase_agreement_template.xml` in this pass |
| Payment plan (deposit/milestones/balance) | ✅ (separate doc) | Fully covered by the existing Payment Schedule report (`payment.schedule` + lines: percentage, days-after-contract, frequency, installments) |
| RERA-monitored escrow account details | ❌ | No field anywhere |
| Estimated completion/handover date + delay penalties | ❌ | No field on `property.details`/`property.project` |
| Oqood interim registration reference | ❌ | No field anywhere |

## 2. Ready/secondary resale (Title Deed transfer) — `sales_purchase_agreement_template.xml`

| Field | Status | Notes |
|---|---|---|
| Title Deed number + property details | ⚠️→✅ | No field existed at all — **added `title_deed_number` to `property.details`** and now rendered in the SPA template |
| Form F / MOU: agreed price, payment terms | ✅ | `sale_price` + Payment Schedule report |
| Deposit ~10% | ⚠️ | `booking_percentage` on `property.details` (default 10.0) is usable as this value but isn't currently surfaced on this report — left as-is, out of scope for this pass (booking flow belongs to Phase 2 model-consolidation work) |
| Developer NOC (dues cleared) | ❌ | No field |
| DLD 4% transfer fee | ⚠️→✅ | Same `dld_fee`/`dld_fee_percentage` fix as above |
| Trustee fee | ❌ | No field |
| Title issuance fee (AED 250) | ❌ | No field |
| Agency commission ~2% | ❌ | `property.vendor.commission_type` selection (percentage/fixed) exists **but there is no field to store the actual commission value** — a real functional gap, flagged for the sales/vendor domain owner, not fixed here (touches commission computation logic outside report scope) |

## 3. Rental (Ejari-style tenancy contract) — **new report**, `rent_contract_report_template.xml`

| Field | Status | Notes |
|---|---|---|
| Landlord name + Title Deed ref | ✅ | `rent.contract.landlord_id` + new `property.details.title_deed_number` |
| Tenant name | ✅ | `tenant_id` |
| Tenant Emirates ID / passport | ❌ | No such field on `res.partner` anywhere in the module |
| Property address, Makani, DEWA premises | ⚠️→✅ | Address existed; **added `makani_number` and `dewa_premises_number` to `property.details`** |
| Type / size | ✅ | From `property_id` |
| Annual rent AED | ✅ | `rent_amount` |
| Payment schedule / cheque count | ⚠️→✅ | `payment_frequency` existed; **added `payment_cheque_count`** to `rent.contract` |
| Security deposit (5% unfurnished / 10% furnished) | ⚠️→✅ | `security_deposit` (absolute amount) existed; **added `furnished_status`** so the basis is visible — no automatic % validation implemented (informational only) |
| Contract duration | ✅ | `start_date`/`end_date`/`duration_months` |
| Maintenance responsibility split | ⚠️→✅ | **Added `maintenance_responsibility`** (landlord/tenant/shared) to `rent.contract` |
| Renewal terms | ⚠️ | `renewal_requested` boolean exists; no free-text renewal terms field — kept as-is (matches existing model depth) |
| Ejari registration number | ⚠️→✅ | **Added `ejari_registration_number`** to `rent.contract` |
| Optional inventory list | ❌ | Not implemented — explicitly optional in the checklist, skipped |

**Confirmed:** this module had **no dedicated rental tenancy contract report** before this pass — the only rental-adjacent documents were the generic invoice and statement of account.

## 4. Maintenance/AMC contract — **new report**, `maintenance_contract_report_template.xml`

| Field | Status | Notes |
|---|---|---|
| Parties + property covered | ✅ | `maintenance.request`'s existing `customer_id`/`vendor_id`/`landlord_id`/`tenant_id`/`property_id` |
| Scope of work (HVAC, electrical, plumbing, fire/life safety, lifts/generators) | ⚠️→✅ | **Added `scope_of_work`** (free text) to `maintenance.request` |
| Service schedule (PPM frequency, named site supervisor) | ⚠️→✅ | **Added `service_frequency`, `site_supervisor_id`** |
| SLA (reactive callout response times) | ⚠️→✅ | **Added `sla_response_hours`** |
| SLA (monthly condition reports) | ❌ | Not modeled — no recurring report artifact tracked, skipped as lower priority |
| Cost breakdown: annual fee | ⚠️→✅ | **Added `annual_fee`**; existing `total_untaxed_amount`/product lines also rendered |
| AMC (labour-only) vs CMC (all-inclusive) | ⚠️→✅ | **Added `amc_contract_type`** selection |
| Exclusions | ⚠️→✅ | **Added `exclusions`** (free text) |
| Duration/renewal | ⚠️→✅ | **Added `contract_start_date`/`contract_end_date`**; no renewal-terms field added (matches rental report's depth) |
| Liabilities | ❌ | Not modeled, skipped |

**Confirmed:** this module had **no dedicated maintenance/AMC contract report** before this pass — `maintenance.request` only had ad-hoc invoice/bill generation, no printable contract document.

## 5. Cross-cutting

| Item | Status |
|---|---|
| All monetary amounts shown in AED | ✅ Confirmed across all 8 templates — every amount is explicitly `'AED %s' % ...`-formatted |
| RERA project registration / DLD M-code | ❌ Not modeled anywhere in the codebase (not just missing from reports) |
| Escrow disclosure (off-plan) | ❌ Not modeled |
| Construction completion % | ❌ Not modeled on `property.project`/`property.details` |
| Broker RERA/BRN numbers | ❌ Not modeled on `res.partner` |
| `web.report_assets_common` CSS bundle | ✅ Confirmed automatically included for **all 8** reports — every template calls `web.html_container`, which chains to `web.report_layout`, which itself calls `t-call-assets="web.report_assets_common"`. No manual xpath/reference needed. |
| Paper size | ⚠️→✅ | All 7 `ir.actions.report` records in `data/report_actions.xml` were bound to `base.paperformat_us` (US Letter) — wrong region for a UAE-facing suite. **Changed all 7 to `base.paperformat_euro` (A4)**, the regional standard. |
| Header/footer/logo consistency | ❌ Not fixed (see below) |

### Header/footer/logo — flagged, not fixed
None of the 8 templates use a shared `external_layout`/company-logo/page-number band. Only
`sales_offer_template.xml` and `statement_of_account_template.xml` print the company name (as
plain text, no logo) in a `col-6 text-right` header block; the other 6 have no company branding
at all, and **none** of the 8 print page numbers or a signature-block footer.

Contrast with the sibling `sgc_construction_management` module's `construction_report_layout.xml`,
which defines a shared `external_layout` template (header band with logo + company address,
footer band with signature lines + page X of Y) driven by a dedicated `report.paperformat` record
and scoped CSS in `web.report_assets_common`. Adopting that same pattern here would be the natural
follow-up for full UAE-document-standard polish, but it's a suite-wide restructuring of all 8
report actions/templates plus a new CSS asset — bigger than this pass's audit + 2-new-reports +
print-QA scope. Recommended as a follow-up task, not attempted here to avoid touching every
existing report's visual structure without a dedicated review pass.

---

## Fixes applied in this pass

**New fields** (require the pending module upgrade to take effect — not yet exposed on any form
view, which is a separate follow-up task):
- `property.details`: `makani_number`, `dewa_premises_number`, `title_deed_number`
- `rent.contract`: `ejari_registration_number`, `furnished_status`, `maintenance_responsibility`, `payment_cheque_count`
- `maintenance.request` (via `models/core/maintenance.py`): `amc_contract_type`, `scope_of_work`, `service_frequency`, `site_supervisor_id`, `sla_response_hours`, `contract_start_date`, `contract_end_date`, `annual_fee`, `exclusions`

**New reports:**
- `report/rent_contract_report_template.xml` — Tenancy Contract (Ejari-style), bound to `rent.contract`
- `report/maintenance_contract_report_template.xml` — Maintenance/AMC Contract, bound to `maintenance.request`
- Both registered as `ir.actions.report` in `data/report_actions.xml` and loaded in `__manifest__.py`

**Existing-report fixes:**
- `sales_purchase_agreement_template.xml`: now renders Title Deed number and DLD fee (fields existed on the model but were never wired into any template)
- All 7 report actions: paper format changed from US Letter to A4 (`base.paperformat_euro`)
- Overflow-risk guards (`word-break:break-word`, `page-break-inside:avoid`) added to free-text/description cells in `sales_offer_property_template.xml`, `statement_of_account_template.xml`, `payment_schedule_template.xml`, and both new templates

## Print-layout QA — all 8 reports

Checked each for: field-overlap risk in narrow table cells, table page-break behavior, header
style consistency, and `web.report_assets_common` inclusion.

| Report | Overlap risk | `page-break-inside:avoid` | Notes |
|---|---|---|---|
| Sales Offer (`property.vendor`) | Low — short fields only | n/a (short tables) | No branding header issue beyond the cross-cutting gap above |
| Sales Offer (`property.details`) | Was medium (`description` Text field, unguarded) | Added | Fixed with `word-break` |
| Sales Purchase Agreement | Low | n/a | Now includes Title Deed + DLD fee rows |
| Statement of Account | Was medium (`line.name`/`description` in narrow cell) | Added | Fixed |
| Payment Schedule | Was medium (`line.name` in narrow cell) | Added | Fixed |
| Invoice inherit (`account.report_invoice_document` xpath) | Low | n/a | Property names have spaces so default wrapping applies; `mw-100` already caps width |
| Tenancy Contract (new) | Guarded from the start | Yes, on every table | `notes` (Text) and `address` wrapped |
| Maintenance Contract (new) | Guarded from the start | Yes, on every table | `scope_of_work`/`exclusions` (Text) and product-line descriptions wrapped |

**Live PDF rendering: not performed.** I have shell access to the `demo_presentation` container,
but the sandbox's auto-mode classifier blocked reading the container's Odoo config (needed to
safely invoke a report render), and — more fundamentally — none of this pass's model-field or
report-action changes are registered in the running database until the module is upgraded, which
the team lead is explicitly coordinating post-round. **Live wkhtmltopdf rendering verification of
all 8 reports (2 new + 6 fixed) is pending that upgrade** — this pass is a thorough static review
only, per the fallback instruction.
