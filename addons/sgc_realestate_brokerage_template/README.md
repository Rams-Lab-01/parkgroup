# SGC Realestate Brokerage Template

A reusable, audit-driven Odoo template for real-estate brokerage tenants
(brokerage-core, growth, offplan-rental, construction-management, full ERP
rollout).

## What this is

This is **not** a full ERP. It's a **tenant skeleton**: a per-tenant record, a
kit-selection model, a preflight check, a set of audit-safe `ir.config_parameter`
defaults, and view + security scaffolding.

It is the entry point for `docs/REAL_ESTATE_BROKERAGE_ROLLOUT.md`, the eight-phase
playbook that turns a fresh Odoo estate into a real-estate brokerage deployment.

## Compatibility

This addon is **versioned against** the SGC estate's audit phase outputs:

- `audit_out/FULL_AUDIT_SUMMARY_REPORT.md` (canonical narrative)
- `phase10d/lender_pack.md` (final headline figures)
- `docs/audit/MODULE_PROVENANCE.md` (per-module status)
- `30_QUARANTINE/README.md` (hold list)

It contains no quarantined module in `depends` and replaces four of the five hardcoded-coupling patterns the audit flagged with `ir.config_parameter` lookups.

## Quickstart (operator)

```bash
# 1. Verify the Lint tool passes
python tools/audit_coupling_lint.py \
    --addons-path ./addons \
    --include-path ./sgc_realestate_brokerage_template \
    --report-md docs/audit/lint_report.md

# 2. Install the template
./odoo-bin -d <dbname> -i sgc_realestate_brokerage_template \
    --addons-path=./addons,./sgc_realestate_brokerage_template \
    --stop-after-init

# 3. Create a tenant in the template's UI:
#    Real Estate → Tenants → New
#    Fill in `Identification` and `Audit-driven per-tenant URLs`.
# 4. Click "Start onboarding", then "Activate (preflight)".
#    The preflight runs the M1/M3/M5/M0 checks from
#    docs/audit/MULTI_TENANT_BLOCKERS.md.
```

## Quickstart (developer)

Models to read in order:

1. `models/sgc_brokerage_tenant.py` — the per-tenant record + preflight.
2. `models/sgc_brokerage_kit.py` — the curated bundle model.
3. `data/ir_config_parameter_defaults.xml` — the placeholder defaults.
4. `data/realestate_growth_defaults.xml` — the pre-baked brokerage kits.

Where the audit's blocker-inventory is enforced:

- `models/sgc_brokerage_tenant.py` `_preflight_check()` — references the
  three blocker classes from `docs/audit/MULTI_TENANT_BLOCKERS.md`.
- `models/sgc_brokerage_tenant.py` `action_activate()` — gates the state
  transition on a passing preflight.

## What this template deliberately excludes

This is the **audit-driven** exclusion list. **No module that the audit holds
appears in `depends` and no held module's `model` is referenced from this
template's Python.**

| Held | Why |
|---|---|
| `ks_dynamic_financial_report` | Provenance unresolved; Ksolves/LGPL-3. |
| `sgc_crm_dashboard` | Foreign-code fingerprint (Cybrosys). |
| `sgc_lead_scoring` | 4 divergent copies + broken unique constraint. |
| `sgc_rental_management` | Staging-only — TechKhedut/SmartClinic. |
| `sgc_construction_management` | Confirmed derivation from `aos_construction_management`. |

Per the audit's `Phase 5` finding, this template does not depend on any held module, by design.

## Roadmap hooks

- **Sibling 1**: `sgc_realestate_brokerage_onboarding` — an onboarding wizard
  that writes per-tenant `ir.config_parameter` keys before activation.
- **Sibling 2**: `sgc_realestate_brokerage_growth` — the growth kit's
  website-builder bridge (connects `sgc_brochure_leadcapture`,
  `sgc_scroll_hero_homepage`, and `sgc_realestate_website` to a per-tenant
  funnel).
- **Sibling 3**: `sgc_realestate_brokerage_erp_rollout` — the enterprise
  reporting + payroll + construction-vertical bundle.

These are not part of this template yet — they are *rollout-phase addons*.

## License

LGPL-3 (matches the audit-recovered Ksolves license for `ks_dynamic_financial_report`
as a marker for what the SGC estate's own reports canonically use, and matches
the OCA community default for vertical addons).
