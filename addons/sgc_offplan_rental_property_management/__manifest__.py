# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
{
    "name": "SGC - Property Management",
    "description": """
        Property Management: Core Management, Portal Syndication & Public Website
        ===============================================================================
        Combines four previously separate, code-dependent SGC modules into one
        application: core property sale (with offplan-style installment payment
        plans) and rental management, multi-portal listing syndication, and the
        public rental website front-end (plus a small CRM-compatibility shim the
        core module relies on).

        Key Features:
        - Property Sale & Management
        - Offplan Installment Payment Plans for Sale & Rental Contracts
        - Lease Contract Management
        - Landlord & Customer Management
        - Property Maintenance
        - Customer Recurring Invoice
        - Flexible Payment Plans
        - Multi-portal listing syndication and lead intake
        - Public rental website with search, filtering, and inquiry capture
    """,
    "summary": "Property Sale & Management with Portal Syndication and Public Website",
    "version": "19.0.2.82",
    "author": "SGC TECH AI",
    "company": "SGC TECH AI",
    "maintainer": "SGC TECH AI",
    "website": "https://sgctech.ai",
    "support": "bran@sgctech.ai",
    "category": "Real Estate",
    "depends": [
        "base",
        "web",
        "mail",
        "contacts",
        "account",
        "hr",
        "maintenance",
        "crm",
        "website",
        "website_mail",
        "portal",
        "sgc_commission",
        "sgc_design_tokens",
    ],
    "data": [
        # Security
        "security/groups.xml",
        "security/critical_audit_groups.xml",
        "security/ir.model.access.csv",
        "security/security.xml",
        "security/portal_groups.xml",
        "security/portal_security.xml",
        "security/critical_audit_security.xml",
        # Report paperformats + shared report design system must load before
        # the report actions / templates that reference them.
        "report/paperformat_data.xml",
        "report/property_report_common.xml",
        # Report ACTIONS must load first (before any views reference them)
        "data/report_actions.xml",
        "data/report_actions_additions.xml",
        "report/commission_summary_template.xml",
        "report/property_brochure_template.xml",
        "report/sale_contract_installment_plan_template.xml",
        # Data
        "data/sequence.xml",
        "data/property_product_data.xml",
        "data/payment_schedule_data.xml",
        "data/website_data.xml",
        "data/property_book_mail_template.xml",
        "data/critical_audit_redaction_baseline.xml",
        "data/critical_audit_verdict_cron.xml",
        # Core views
        "views/core/assets.xml",
        "views/core/rera_form_a_view.xml",
        "views/core/property_details_view.xml",
        "views/core/property_vendor_view.xml",
        "views/core/tenancy_details_view.xml",
        "views/core/property_invoice_inherit.xml",
        "views/core/res_config_setting_view.xml",
        "views/core/property_res_city.xml",
        "views/core/property_region_views.xml",
        "views/core/property_project_views.xml",
        "views/core/maintenance_product_inherit.xml",
        "views/core/property_maintenance_view.xml",
        "views/core/payment_schedule_views.xml",
        "views/core/property_image_views.xml",
        "views/core/property_amenities_view.xml",
        "views/core/property_tag_view.xml",
        "views/core/property_specification_view.xml",
        "views/core/property_document_view.xml",
        "views/core/agreement_template_view.xml",
        "views/core/certificate_type_view.xml",
        "views/core/contract_duration_view.xml",
        "views/core/nearby_connectivity_view.xml",
        "views/core/user_type_view.xml",
        "views/core/rent_bill_view.xml",
        "views/core/rent_invoice_view.xml",
        "views/core/sale_contract_views.xml",
        "views/core/rent_contract_views.xml",
        "views/core/rent_contract_view.xml",
        "views/core/property_crm_lead_inherit_view.xml",
        "views/core/product_product_inherit_view.xml",
        "views/core/account_project_unit_views.xml",
        "views/core/account_payment_inherit.xml",
        # Portal actions must load before core menus.xml (which references portal actions)
        "views/portal/actions.xml",
        "views/core/menus.xml",
        # CRM compatibility views
        "views/compat/crm_lead_views_compatibility.xml",
        # Public website views
        "views/website/property_details_views.xml",
        "views/website/property_website_templates.xml",
        "views/website/snippets.xml",
        "views/website/property_publish_wizard_views.xml",
        "views/website/offplan_property_listing.xml",
        "views/website/offplan_property_detail.xml",
        "views/website/offplan_project_listing.xml",
        "views/website/offplan_project_detail.xml",
        # Portal syndication admin (menus + views)
        "views/portal/menus.xml",
        "views/portal/portal_connector_views.xml",
        "views/portal/portal_sync_log_views.xml",
        "views/portal/xml_feed_config_views.xml",
        "views/portal/portal_lead_views.xml",
        "views/portal/property_details_feed_source_views.xml",
        # Portal frontend views
        "views/portal/portal_my_properties.xml",
        "views/portal/portal_my_contracts.xml",
        "views/portal/portal_my_invoices.xml",
        "views/portal/portal_my_maintenance.xml",
        "views/portal/portal_my_statements.xml",
        "views/portal/portal_my_home_inherit.xml",
        "views/portal/portal_tenant_dashboard.xml",
        "views/portal/portal_landlord_dashboard.xml",
        "views/portal/portal_customer_dashboard.xml",
        # Critical audit views (after core menus.xml defines the root menu the
        # audit menus attach to)
        "views/core/critical_audit_event_views.xml",
        "views/core/critical_audit_event_menus.xml",
        "views/core/critical_audit_verdict_views.xml",
        # Wizard views (loaded after core views)
        "wizard/views/booking_wizard_views.xml",
        "wizard/views/critical_audit_reason_wizard_views.xml",
        "wizard/views/critical_audit_delete_actions.xml",
        "wizard/views/sale_confirm_warning_wizard_views.xml",
        "wizard/views/bulk_creation_wizard_views.xml",
        # Report templates
        "report/property_brochure_luxury_template.xml",
        "report/sales_offer_template.xml",
        "report/sales_purchase_agreement_template.xml",
        "report/sales_offer_property_template.xml",
        "report/invoice_report_inherit.xml",
        "report/statement_of_account_template.xml",
        "report/payment_schedule_template.xml",
        "report/rent_contract_report_template.xml",
        "report/portfolio_statistics_report_template.xml",
        "report/project_summary_report_template.xml",
        "report/critical_audit_verification_report.xml",
        "report/rera_form_a_report_template.xml",
        "report/maintenance_contract_report_template.xml",
        "report/booking_agreement_template.xml",
        # Navigation consolidation re-parents menus AND references report ACTIONS
        # that live in the templates above (e.g. action_report_property_brochure_luxury
        # in property_brochure_luxury_template.xml). It must therefore load after
        # every report template, otherwise a fresh install fails with
        # "External ID not found". Menus stay last among the data files.
        "views/core/navigation_consolidation.xml",
        "data/ir_cron_feed_ingest.xml",
        "data/ir_cron.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sgc_offplan_rental_property_management/static/src/lib/echarts.min.js",
            "sgc_offplan_rental_property_management/static/src/lib/leaflet.css",
            "sgc_offplan_rental_property_management/static/src/lib/leaflet.js",
            "sgc_offplan_rental_property_management/static/src/css/style.css",
            "sgc_offplan_rental_property_management/static/src/xml/template.xml",
            "sgc_offplan_rental_property_management/static/src/scss/style.scss",
            "sgc_offplan_rental_property_management/static/src/js/rental.js",
            "sgc_offplan_rental_property_management/static/src/js/list_renderer_fix.js",
            "sgc_offplan_rental_property_management/static/src/components/**/*",
            "sgc_offplan_rental_property_management/static/src/views/**/*",
        ],
        "web.assets_frontend": [
            "sgc_offplan_rental_property_management/static/src/css/extra.css",
            "sgc_offplan_rental_property_management/static/src/css/property_listing.css",
            "sgc_offplan_rental_property_management/static/src/js/property_search.js",
            "sgc_offplan_rental_property_management/static/src/js/property_carousel.js",
        ],
    },
    "images": [
        "static/description/banner.png",
    ],
    "license": "OPL-1",
    "installable": True,
    "application": True,
    "auto_install": False,
    "price": 399,
    "currency": "USD",
    "post_init_hook": "sgc_offplan_rental_property_management.post_init_hook",
}
