# Changelog

All notable changes to this module are documented in this file.
Format based on Keep a Changelog; versioning follows the module manifest
(`19.0.x.y.z`).

## [19.0.2.12] - 2026-09-04 — Production readiness for live deployment

### Dropped
- `sgc_realestate_website` standalone module: removed from the deliverable by
  owner decision. It queried a non-existent `property.property` model, rendered
  four undefined QWeb templates, used a wrong `t-call` prefix and shipped no
  `main.css`; repair cost exceeded the value of a second public front-end.
- `sgc_rental_portal` standalone module: its models were already merged here;
  installing both modules together causes an ORM registry collision
  (`portal.connector`, `portal.lead`, `portal.sync.log`,
  `property.portal.line`, `xml.feed.config` duplicated).

### Added
- `__manifest__.py` reconstructed (was missing from the packaged tree):
  depends (mail, contacts, product, account, crm, maintenance, portal,
  website), full data/view load order, OPL-1 license, images, banner.
- `models/core/property_wizards.py`:
  - `property.publish.wizard` transient model, reconstructed from its shipped
    form view (`views/website/property_publish_wizard_views.xml`) and launching
    action (`property.details.action_open_publish_wizard`).
  - `booking.wizard` transient model + form view, reconstructing the
    `Create Booking` stat button on `property.project`; creates a
    `property.vendor` booking with a `property.vendor` sequence reference.
- HMAC-SHA256 signature enforcement on the inbound lead webhook
  (`/portal-webhook/<code>`): `portal.connector.webhook_secret` (random,
  `copy=False`, admin-only visibility), `X-SGC-Signature: sha256=<hex>` over
  the raw request body, constant-time comparison, fail-closed on empty secret,
  rejection logging to `portal.sync.log`, and a `Regenerate` button on the
  connector form. Previously the endpoint accepted unauthenticated writes from
  anyone who could guess a portal code.
- Feed pagination on `/portal-feed/<code>`: `offset` and `limit` query
  parameters, default `limit=200`, hard cap `limit=1000`, with `offset`,
  `limit` and `count` attributes echoed in the response XML. Previously a
  portal pulling the full catalogue forced an unbounded in-memory XML build.
- `ops/` ten-tenant production toolkit:
  `provision.sh`, `deprovision.sh`, `backup.sh`, `restore.sh`,
  `upgrade_tenant.sh`, `lib.sh`, `ops.env.example`,
  `fail2ban/odoo-login.conf`. Legacy staging scripts moved to `ops/legacy/`.
  Every backup bundles the database **and the filestore**; bundles are
  integrity-checked before being considered valid.
- `LICENSE` (OPL-1), this `CHANGELOG.md`, and `PRODUCTION.md`.

### Fixed (install blockers — all caught by a live Odoo 19.0 install)
- ACL rows referencing 14 models that do not exist in the codebase (wizards
  and transient helpers dropped during the original merge): rows removed;
  the two reconstructed wizards received proper ACLs. On Odoo 19 these rows
  aborted the install with `null value in column "model_id"`.
- `type="html"` fields containing escaped text (Odoo 19 data-file schema
  requires element children for `type="html"`): attribute removed, which
  stores the identical string.
- `body_html` and `help` fields containing raw XML elements with no `type`:
  set to `type="xml"` (identical stored value, schema-conformant).
- `ir_cron.xml` used the `doall` field, removed from `ir.cron` in Odoo 19.
- `views/core/rent_contract_view.xml` (inherit) loaded before its base view:
  manifest order corrected; XPath `@name='button_box' ` trailing-space typo
  fixed.
- Self-inheriting template `portal_my_lease_detail` with an invalid XPath:
  the `Signed Electronically via Portal` badge was merged into the base
  template (guarded to `rent_contract`), the broken inherit file deleted.
- Dead `Statistics` dashboard menu pointing at client actions
  (`property_dashboard` / `property_availability`) whose OWL components do not
  exist: menu and dead actions removed.
- `Employees` menu cross-referencing `hr.open_view_employee_list_my`: removed
  instead of pulling the `hr` module into `depends`.
- `agreement_template_test.xml` (a literal "Test Template" record shipped as
  production data): deleted.
- `controllers/website.py` (empty stub): deleted.
- Website menu "Properties" pointed at `/properties` where the route is
  `/offplan/properties`: URL corrected.
- Mail templates `active_contract` and `tenancy_reminder` referenced a
  non-existent `tenancy_details_report_id` report action; `property_sold`
  referenced a non-existent `property_sold_report_template_id`. The dangling
  references were removed / repointed to the existing
  `action_report_sales_purchase_agreement`.

### Verified (real runtime, Odoo 19.0 source build)
- Fresh database install: `Modules loaded.` with zero errors.
- Upgrade pass (`-u`): zero errors, idempotent.
- Live HTTP: `/web/login` 200, `/offplan/properties` 200 public,
  `/my/dashboard` 200 authenticated (portal user login round-trip).
- `/portal-feed/<code>`: 401 without token, 200 with token, pagination
  attributes present.
- `/portal-webhook/<code>`: unsigned and wrong-signature payloads rejected;
  a correctly signed payload creates a `portal.lead` (verified in DB).
- `portal.connector` ORM create auto-seeds random `webhook_secret` and
  `xml_feed_token` per record (per-database isolation follows from one DB per
  tenant).

## [19.0.2.3] - historical
- Post-migration cleanup of orphaned DB-only kanban views referencing the
  removed pre-Odoo-17 `kanban_getcolor` helper (see
  `migrations/19.0.2.3/post-migrate.py`).

## [19.0.2.12] - historical
- Deletion of orphaned `property.details` kanban views referencing
  `kanban_getcolor` on upgraded databases (see
  `migrations/19.0.2.12/post-migrate.py`).
