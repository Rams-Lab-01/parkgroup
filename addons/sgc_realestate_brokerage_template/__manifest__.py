# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template.
# See LICENSE file for full copyright and licensing details.
{
    "name": "SGC Realestate Brokerage Template",
    "summary": "Reusable real-estate brokerage core + growth baseline and full-ERP-rollout onboarding pack.",
    "version": "19.0.1.1.0",
    "category": "Real Estate / Brokerage",
    "author": "Scholarix Global Consultants -FZCO",
    "website": "https://www.sgctech.ai",
    "license": "LGPL-3",
    "depends": [
        # Vertical core — proven SGC_OWNED audit-class modules (see
        # docs/audit/MODULE_PROVENANCE.md). Add or remove per vertical scope.
        "crm",
        "account",
        "sale_management",
        "contacts",
        "website",
        "hr",
        # SGC-owned building blocks (NOT in the audit hold-list):
        "aml_compliance",
        "kyc_management",
        "sgc_appraisal",
        "sgc_ces_kpi_banner",
        "sgc_design_tokens",
        "sgc_ui_brand_palette",
        "sgc_dynamic_financial_report",
    ],
    "excludes": [
        # Audit-quarantined modules (see 30_QUARANTINE/README.md).
        # Reference these only via --addons-hold-path, never via the normal
        # prod addon path. The template composes no held module in `depends`.
        "ks_dynamic_financial_report",
        "sgc_crm_dashboard",
        "sgc_lead_scoring",
        "sgc_rental_management",
        "sgc_construction_management",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_config_parameter_defaults.xml",
        "data/realestate_growth_defaults.xml",
        # Views MUST load before menus — menus reference actions defined
        # in the view files below (verified via clean-room install test,
        # 2026-08-31: a prior ordering loaded menus first and broke
        # installation with `ValueError: External ID not found in the
        # system: sgc_realestate_brokerage_template.action_sgc_brokerage_tenant`).
        "views/template_views.xml",
        "views/reconciled_views.xml",
        "views/template_menus.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,  # match audit-safe pattern from ks_dynamic_financial_report recovery
    "sequence": 100,
    "description": """
SGC Realestate Brokerage Template
=================================

A reusable, audit-driven template for any real-estate brokerage tenant. It does
*not* ship a full ERP — it ships the **onboarding skeleton**, the **parametrised
defaults**, and the **tenant lifecycle hooks** that wire an existing SGC estate
into a per-tenant real-estate brokerage deployment.

Architecture
------------

1.  ``sgc.brokerage.tenant`` (model ``sgc_realestate_brokerage_template``) —
    the per-tenant record. One row per real-estate tenant. Holds the
    enablement flags for: core (sales, lead-scoring, listings, deals,
    commission); growth (CRM dashboard, nurture, broker portal); and ERP
    rollout (AML, KYC, offplan rental, construction gating, payroll).

2.  ``sgc.brokerage.kit`` — the bundle-selection model. Each
    ``kit`` is a curated subset of the SGC estate proven to compose for a
    vertical (brokerage-core, offplan-rental, construction, recurring-Mgmt).
    Kits are referenced from M2O on the tenant.

3.  ``ir.config_parameter`` defaults — the placeholder values that the
    template ships. Real values are filled in by the tenant onboarding
    wizard (see ``onboarding_*.xml`` in companion addons) before first use.

4.  SQL/CSV preflight checks — each model in this addon exposes a
    ``*_preflight_check()`` method that the audit's

    ::

        tools/audit_coupling_lint.py

    surfaces. See ``docs/audit/MULTI_TENANT_BLOCKERS.md`` for the M1/M3/M5
    inventory this template is designed to be compatible with.

Compliance
----------

This addon references the audit's hold list (``30_QUARANTINE/README.md``) by
exact ``excludes`` entry above. **No held module is in ``depends``** — the
template composes only audit-cleared modules from
``docs/audit/MODULE_PROVENANCE.md``.

Hardcoded emails and localhost URLs that the audit's
``audit_out/coupling_findings.csv`` flagged have been replaced by
``ir.config_parameter`` lookups in this template. See
``data/ir_config_parameter_defaults.xml`` for the canonical key list.

Rollout phases
--------------

This template is the entry point for ``docs/REAL_ESTATE_BROKERAGE_ROLLOUT.md``,
which describes eight phases of a real-estate brokerage deployment.

The ``sequence = 100`` above keeps the template at the top of any addon-index
that sorts by sequence, so the kit-selector menu entry is visible early in any
real-estate vertical installation.
    """,
    "post_load": None,
}
