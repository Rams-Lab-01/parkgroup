# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
{
    "name": "SGC - Property Lead Journey",
    "version": "19.0.1.0.0",
    "summary": "Single, governed CRM lead spine for property sales (lead -> EOI -> booking -> SPA)",
    "description": """
SGC Property Lead Journey
=========================

Closes the gap between the CRM pipeline and the property-management sale
instruments so the customer journey is one connected spine instead of
fragmented islands:

    website / portal / call
            |  (property_id set, never orphaned)
            v
        crm.lead  --(EOI)-->  sale.contract['eoi']
            |  --(booking)-->  sale.contract['booked'/'confirmed']
            |  --(SPA)--------> sale.contract['spa_signed']  =>  lead Won

What it adds
------------
* ``sale.contract.lead_id`` — the missing link from the sale instrument back
  to the lead/opportunity, with smart buttons on the lead form.
* Automatic stage hand-off: creating an EOI / booking / signing the SPA advances
  the linked lead's stage, so the CRM pipeline always reflects reality.
* The EOI and booking wizards carry the originating lead through to the
  contract (opened from a lead form, or pre-selected from the property).
* Website inquiry intake now links the created ``crm.lead`` to the property
  (``property_id``) and back-links ``property.website.inquiry.lead_id``.
* A governed, role-aware navigation: **Leads** (all) + **Opportunities**.
* Journey SLA fields (days in stage) for internal control and dashboards.

Deliberately additive: it inherits — never rewrites — the property, EOI and CRM
models, so it can be installed/uninstalled without touching the tenant's data.
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
        "crm",
        "sale_management",
        "website",
        "sgc_offplan_rental_property_management",
        "sgc_property_eoi_workflow",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/crm_lead_views.xml",
        "views/sale_contract_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
