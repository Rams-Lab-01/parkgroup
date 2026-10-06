{
    "name": "SGC PDC & Cheque Management",
    "version": "19.0.1.0.0",
    "category": "Accounting/Property Management",
    "summary": "Post-dated cheque (PDC) register integrated with property sales, "
               "tenancies and rent invoices, with Odoo + email alerts for "
               "upcoming and matured cheques.",
    "author": "SGC TECH AI",
    "license": "OPL-1",
    "depends": [
        "account",
        "mail",
        "sgc_offplan_rental_property_management",
    ],
    "data": [
        "security/pdc_groups.xml",
        "security/ir.model.access.csv",
        "security/pdc_rules.xml",
        "data/mail_templates.xml",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "wizard/pdc_bounce_wizard_views.xml",
        "views/pdc_cheque_views.xml",
        "views/res_config_settings_views.xml",
        "views/integration_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
