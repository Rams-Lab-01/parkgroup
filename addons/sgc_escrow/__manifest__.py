# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
{
    "name": "SGC - Escrow Bridge (Property Management <-> Accounting)",
    "description": """
Escrow bridge between the Property Management module and Accounting
===

Connects `property.project` / `property.details` / `sale.contract` to the
Odoo general ledger so that off-plan buyer money held in a project escrow
account can be tracked, capped by certified construction progress, and
released against bank approval.

**Key Features:**

- Per-project escrow configuration (bank journal, escrow agent, retention %)
- Per-unit escrow allocation register (the auditable record of who paid what into escrow, incl. historic facts loaded from external statements)
- Ledger-driven roll-ups (received / released / balance / entitlement / releasable-now) computed from `account.move.line`, never shadow tables
- Release documents gated by certified construction progress minus retention (the standard statutory control); over-release blocked unless overridden by an Escrow Manager with a mandatory reason
- Payment routing: "Register Payment" defaults to the project's escrow journal, with a configurable warn / block / off policy guard
- Unit escrow tab and QWeb escrow statements for the escrow bank / auditor

**Design principles:**

- No parallel subledger: the Odoo ledger IS the escrow ledger
- The `account` application is extended by inheritance only, never patched
- Every field defaults to today's behaviour (escrow off), so installation is additive and fully reversible
    """,
    "summary": "Escrow bridge between Property Management and Accounting with progress-gated releases",
    "version": "19.0.1.0.0",
    "author": "SGC TECH AI",
    "company": "SGC TECH AI",
    "maintainer": "SGC TECH AI",
    "website": "https://sgctech.ai",
    "support": "bran@sgctech.ai",
    "category": "Real Estate",
    "depends": [
        "account",
        "sgc_offplan_rental_property_management",
    ],
    "data": [
        # Security first: groups must exist before ACL rows reference them.
        "security/escrow_groups.xml",
        "security/ir.model.access.csv",
        "security/ir.rule.csv",
        # Sequences
        "data/escrow_sequence.xml",
        # Report paperformat must load before the report actions that use it.
        "report/escrow_paperformat.xml",
        # Inherited core views
        "views/property_project_view.xml",
        "views/property_details_view.xml",
        "views/sale_contract_view.xml",
        "views/account_move_view.xml",
        # Module-owned views
        "views/escrow_allocation_views.xml",
        "views/escrow_release_views.xml",
        "views/res_config_setting_view.xml",
        # Report actions must exist before menus reference them.
        "data/report_actions.xml",
        # Menus last (they reference the actions above)
        "views/menus.xml",
        # Wizard
        "wizard/views/escrow_allocation_import_views.xml",
        # QWeb templates
        "report/escrow_project_statement_template.xml",
        "report/escrow_allocation_register_template.xml",
        "report/escrow_release_voucher_template.xml",
    ],
    "license": "OPL-1",
    "installable": True,
    "application": False,
    "auto_install": False,
    "price": 0,
    "currency": "USD",
}