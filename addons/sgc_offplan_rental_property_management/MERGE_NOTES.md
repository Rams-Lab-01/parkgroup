# Merge Notes: sgc_offplan_rental_property_management

This module combines 4 previously separate SGC modules that had a real, code-level dependency chain (confirmed by reading each manifest's `depends` list, not just by category/theme):

```
sgc_crm_ai_compat  →  sgc_rental_management  →  sgc_rental_portal
                                              →  sgc_rental_website
```

No other modules in the SGC suite have a genuine `sgc_*` entry in their `depends` list — this was the only real dependency cluster found.

## Structure

To avoid filename collisions across the 4 source modules (e.g. two unrelated `portal_connector.py` files), models are organized into subpackages:

- `models/compat/` — from `sgc_crm_ai_compat` (1 file, extends `crm.lead`)
- `models/core/` — from `sgc_rental_management` (25 files, ~20 new models)
- `models/portal/` — from `sgc_rental_portal` (7 files)
- `models/website/` — from `sgc_rental_website` (2 files; a 3rd file, a dead `portal.connector` stub left over from an Odoo 19 model removal, was intentionally not carried over)

Views, controllers, wizards, data, and security files follow the same `core/`/`portal/`/`website/`/`compat/` split where applicable.

## Fixes applied as part of the merge

- **ACL gap closed.** `sgc_crm_ai_compat` and `sgc_rental_management` were both flagged in the readiness audit as missing `security/ir.model.access.csv` entirely. The merged module's ACL CSV adds entries for all ~20 of `sgc_rental_management`'s previously-unprotected models, using the existing `property_rental_officer`/`property_rental_manager` groups already defined in its `security/groups.xml`.
- **Cross-module xmlid/config_parameter references repointed.** All `sgc_rental_management.*`, `sgc_rental_portal.*` references across Python (`env.ref()`, `ir.config_parameter` keys), XML (`ref=` attributes, `eval` blocks), and JS (`@module/...` asset import aliases, OWL template names) were renamed to `sgc_offplan_rental_property_management.*` (or bare local IDs where Odoo's same-module XML resolution allows it). Verified by grepping the entire merged module for the old module names after the rename — zero remaining matches.
- **Missing static asset added.** `sgc_rental_website`'s frontend CSS/JS (`property_listing.css`, `property_search.js`) were referenced in its original manifest's `assets` but hadn't been copied in the first packaging pass — added.
- **Broken `images` reference fixed.** `sgc_rental_management`'s original manifest pointed `images` at `static/description/property-rental.gif`, which doesn't exist anywhere in the source module either — this was a pre-existing defect, not something the merge introduced. Repointed to `banner.png`, which does exist.

## Pre-existing defects found and documented, NOT fixed (out of scope for packaging)

- **`sgc_rental_website`'s controller renders 3 QWeb templates that don't exist anywhere in that module**: `rental_listings`, `rental_detail`, `thank_you` (referenced via `request.render(...)` in `controllers/main.py`). Every route in that controller (`/rental/listings`, `/rental/property/<id>`, `/rental/thank-you`) would raise a template-not-found error at runtime. This is inherited from the original `sgc_rental_website` module, not introduced by the merge. Not fixed here — fabricating template content would mean inventing functionality, which the packaging task explicitly prohibits. Flagged for the dev team to fix in the source module.
- **`sgc_rental_management`'s original manifest already had `"price": 250, "currency": "USD"` set while licensed LGPL-3** — a real, already-existing instance of the exact license/price violation this whole project's pricing research is about. Discovered after the initial audit (which used a single-quote-only grep and missed double-quoted price keys — corrected in `pricing_research/02_module_audit.md`).
- `sgc_rental_management/controllers/main.py` (carried into this module) and the old `sgc_rental_website/controllers/main.py` both use CR-only line endings, not LF — unusual but not a syntax error (confirmed via `ast.parse`); left as-is.

## Verification performed (static checks only — no Odoo runtime available)

- `python -m py_compile` on every `.py` file in the module — all pass.
- `ast.literal_eval` on `__manifest__.py` — parses to a valid dict.
- `xml.etree.ElementTree.parse` on all 51 XML files — all well-formed.
- Cross-checked every `data`/`assets`/`images` path in the manifest against the filesystem — all exist (after the 2 fixes above).
- Grepped for duplicate `_name =` model declarations across all 4 source subpackages — none found.
- Grepped for duplicate `@http.route()` paths across all 3 controller files — none found.

**Not verified** (would require a live Odoo 19.0 instance, explicitly out of scope): actual module installation, ORM field resolution, view rendering, ir.rule/ACL enforcement at runtime, JS asset bundling.

## Pricing

First-document prices for the 4 source modules: `sgc_rental_management` $75, `sgc_rental_portal` $45, `sgc_rental_website` $25, `sgc_crm_ai_compat` $25 — sum $170. `sgc_rental_management`'s own (LGPL-3, therefore non-executable) manifest had priced itself at $250 standalone. Combined suite price set to **$399**, reflecting: higher than either reference sum, broader functionality than any single competitor found in market research (the closest comparable, `dev_property_management` at $90.50, covers similar scope but as one already-integrated app rather than 4 merged modules), and the value of having portal syndication + public website bundled with core management rather than sold/maintained separately.
