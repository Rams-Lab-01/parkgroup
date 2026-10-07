# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
{
    "name": "SGC - Real Estate Dashboard",
    "version": "19.0.1.0.0",
    "summary": "SGC-owned real-estate dashboard for the property-sale journey (units, contracts, collections, escrow)",
    "description": """
SGC Real Estate Dashboard
=========================

A purpose-built, SGC-owned dashboard for a real-estate developer, replacing the
foreign (Cybrosys-fingerprinted) generic CRM dashboard that the multi-tenant
audit quarantined. Every figure is aggregated live from real records:

  * Inventory        — property.details by state (available/booked/sold/eoi)
  * Sales            — sale.contract by state, sales value, signed value
  * Collections      — sale.contract.installment (paid / outstanding)
  * Escrow           — escrow.allocation required vs allocated (shortfall)
  * Journey funnel   — leads -> EOI -> booking -> SPA (crm.lead + contract)
  * Pipeline aging   — open opportunities by days-in-stage (SLA control)

Each card/chart is clickable and opens the exact record list behind the number
(``open_records`` returns a real ``ir.actions.act_window``).

No hardcoded numeric stage ids — stages are resolved by name so the module is
portable across tenants.
""",
    "author": "SGC TECH AI",
    "company": "SGC TECH AI",
    "maintainer": "SGC TECH AI",
    "website": "https://sgctech.ai",
    "support": "bran@sgctech.ai",
    "category": "Real Estate",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "crm",
        "sale_management",
        "sgc_offplan_rental_property_management",
        "sgc_property_eoi_workflow",
        "sgc_escrow",
        "sgc_property_lead_journey",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sgc_realestate_dashboard/static/src/dashboard/dashboard.scss",
            "sgc_realestate_dashboard/static/src/dashboard/dashboard.xml",
            "sgc_realestate_dashboard/static/src/dashboard/dashboard.js",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
