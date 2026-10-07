# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
{
    "name": "SGC - CRM & Marketing Dashboard",
    "version": "19.0.1.0.0",
    "summary": "Live CRM pipeline, potential-buyer and campaign/marketing-ROI dashboard for real estate",
    "description": """
SGC CRM & Marketing Dashboard
=============================

One SGC-owned board that answers three questions a real-estate sales/marketing
lead actually asks, with every figure aggregated live from real records:

1. **Potential buyers** — open opportunities, pipeline value, weighted pipeline,
   where each buyer is (stage / owner / source), and who the biggest live
   buyers are, with drill-down to the exact leads.
2. **Campaigns** — per-campaign leads, opportunities, wins.
3. **Marketing ROI** — attributable revenue (from the sale contracts linked to
   each campaign's leads), campaign spend, cost-per-lead, cost-per-acquisition
   and ROAS — the numbers that decide where the next dirham goes.

Attribution model
-----------------
``crm.lead`` carries ``campaign_id`` / ``source_id`` / ``medium_id`` /
``expected_revenue`` (CRM standard). Revenue is attributed to a campaign through
the property-sale contract linked to the winning lead
(``sale.contract.lead_id``, added by ``sgc_property_lead_journey``). Campaign
spend is captured on ``utm.campaign.marketing_cost`` (added here).

No hardcoded/placeholder data; stages resolved by name (portable across tenants).
Complementary to the property-operations dashboard in
``sgc_offplan_rental_property_management`` — this one is CRM/marketing, that one
is inventory/sales/collections/escrow.
""",
    "author": "SGC TECH AI",
    "company": "SGC TECH AI",
    "maintainer": "SGC TECH AI",
    "website": "https://sgctech.ai",
    "support": "bran@sgctech.ai",
    "category": "Sales/CRM",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "crm",
        "sale_management",
        "utm",
        "sgc_property_lead_journey",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/dashboard_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sgc_crm_marketing_dashboard/static/src/dashboard/dashboard.scss",
            "sgc_crm_marketing_dashboard/static/src/dashboard/dashboard.xml",
            "sgc_crm_marketing_dashboard/static/src/dashboard/dashboard.js",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
