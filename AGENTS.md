# AGENTS — Parkgroup Odoo Addons

## Project Overview
This repository contains custom Odoo 19 addons for Parkgroup's real estate brokerage platform.

## Odoo Version
**Target: Odoo 19**. The manifests declare version `19.0.x.x`. All code uses Odoo 17+ idioms
(`from odoo.fields import Domain`, `models.Constraint`, `models.UniqueIndex`).

## Module Layout
```
addons/
  sgc_pdc_management/          — Post-dated cheque (PDC) register and alerts
  sgc_broker_registration/     — UAE broker onboarding portal + compliance
  sgc_escrow/                  — Escrow management
  sgc_offplan_rental_property_management/  — Base property/tenancy module (dependency)
  sgc_property_lead_journey/   — CRM lead spine for property sales (lead → EOI → booking → SPA)
  sgc_crm_marketing_dashboard/ — CRM/marketing dashboard (potential buyers, campaigns, ROI)
```

## Key Dependencies
- `sgc_pdc_management` depends on `sgc_offplan_rental_property_management` (sale.contract, tenancy.details, rent.invoice, property.details)
- `sgc_broker_registration` depends on `base`, `mail`, `contacts`, `portal`, `website`
- `sgc_property_lead_journey` depends on `crm`, `sale_management`, `website`, `sgc_offplan_rental_property_management`, `sgc_property_eoi_workflow` — links `sale.contract.lead_id` to `crm.lead` and drives the lead stage from the contract state
- `sgc_crm_marketing_dashboard` depends on `crm`, `utm`, `sgc_property_lead_journey` — CRM/marketing analytics (pipeline, campaigns, ROI); adds `utm.campaign.marketing_cost`. Complementary to the property-operations dashboard in `sgc_offplan_rental_property_management` (`Property Management → Statistics`); the old `sgc_realestate_dashboard` was retired as a duplicate of that one

## Testing
Tests are tagged `post_install` (`-at_install`), so they run after all modules are installed.

### Run all module tests
```bash
odoo-bin -d <db> -i sgc_pdc_management,sgc_broker_registration --test-enable --stop-after-init
```

### Run a specific test class
```bash
odoo-bin -d <db> --test-enable --stop-after-init \
  --load=web,python3 -i sgc_pdc_management,sgc_broker_registration \
  --test-tags="post_install" \
  -r root -p odoo
```

### Test files
- `addons/sgc_pdc_management/tests/test_pdc.py` — workflow, cron batching, access rights, reports
- `addons/sgc_broker_registration/tests/test_portal_flow.py` — full HTTP portal flow, abuse protection
- `addons/sgc_broker_registration/tests/test_validators.py` — email/phone/IBAN/Emirates ID validators

## Production Deployment Notes

### Required `odoo.conf` settings
```ini
proxy_mode = True          # Required: captures real client IP for IP rate-limiting
database.secret = <strong-secret>  # Required: HMAC-SHA256 hashing of verification codes
```

### Mail queue
- Both modules use `force_send=False` for transactional emails (queued).
- Ensure the mail queue cron (`ir.cron delivery` / `Mail Queue`) is active.
- Configure `mail.catchall.domain` and valid `email_from` for outbound mail.

### Cron jobs
Two daily cron jobs are created on install:
- **PDC**: `PDC: notify upcoming and matured cheques` — `sgc.pdc.cheque._cron_notify_cheques()`
- **Broker**: `Broker compliance: licence and document expiry alerts` — `sgc.broker.application._cron_check_expiries()`

Both use progressive batch commits and will auto-resume via the scheduler on large datasets.

### Multi-company
- PDC cheques are multi-company (`company_id` record rule).
- Broker applications are single-tenant (UAE regulatory context).

## Common Commands
- **Upgrade a single module**: `odoo-bin -d <db> -u sgc_broker_registration --stop-after-init`
- **Install a module**: `odoo-bin -d <db> -i sgc_pdc_management --stop-after-init`
- **Check module status**: SQL: `SELECT name, state, latest_version FROM ir_module_module WHERE name LIKE 'sgc_%'`
