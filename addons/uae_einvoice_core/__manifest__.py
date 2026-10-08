# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    "name": "UAE E-Invoicing Core",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "summary": "PINT-AE canonical invoice model, flag engine, and validator for UAE e-invoicing compliance",
    "author": "UAE E-Invoicing Contributors",
    "maintainer": "UAE E-Invoicing Contributors",
    "website": "https://github.com/uae-einvoicing/uae_einvoice_core",
    "category": "Accounting/Localizations",
    "depends": [
        "account",
        "l10n_ae",
    ],
    "external_dependencies": {
        "python": [],
    },
    "data": [
        "security/ir.model.access.csv",
        "data/document_type_codes.xml",
        "data/predefined_endpoints.xml",
        "views/res_partner_views.xml",
        "views/account_move_views.xml",
    ],
    "qweb": [
        "xml_templates/pint_ae_ubl_invoice.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
