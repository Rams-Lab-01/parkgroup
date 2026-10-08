# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
{
    "name": "SGC - Project Costing",
    "summary": "Analytic-account project costing, budgeting and collection timeline for property.project",
    "description": """
Project Costing
===============
Adds analytic-account based costing to ``property.project``: construction /
development costs tracked OUT, mirroring the escrow module which tracks buyer
money IN.

Following the escrow module's design principles, every financial figure is a
query over the standard analytic ledger (``account.analytic.line``) and the
purchase commitments that carry an analytic distribution. There is no shadow
subledger to reconcile.

Features
--------
- One analytic account per project, grouped under a "Property Development" plan
- Budget vs costed vs committed vs remaining
- Cost / collection milestone timeline
- Project health (cash position, burn rate, variance) and QWeb cost report
    """,
    "author": "SGC TECH AI",
    "company": "SGC TECH AI",
    "website": "https://sgctech.ai",
    "category": "Real Estate",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "depends": [
        "account",
        "analytic",
        "purchase",
        "sgc_offplan_rental_property_management",
        "sgc_escrow",
    ],
    "data": [
        # Security first: groups must exist before ACL rows reference them.
        "security/project_costing_groups.xml",
        "security/ir.model.access.csv",
        # Actions (report + windows) before views/menus reference them.
        "data/ir_actions.xml",
        # Inherited core views.
        "views/core/property_project_costing_views.xml",
        # Wizard view/action.
        "wizard/project_start_wizard.xml",
        # QWeb report template must exist before the report action prints it.
        "reports/project_cost_report.xml",
        # Menus last (they reference the actions above).
        "views/menus.xml",
    ],
    "demo": [],
    "installable": True,
    "application": True,
    "auto_install": False,
}
