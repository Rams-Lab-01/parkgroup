{
    "name": "SGC PGRE Financial Sync",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "summary": "One-way financial-data sync engine pulling deltas from remote Odoo 18 (pgre.odoo.com) "
               "and mirroring into local Odoo 19 (account.move + lines, account.payment) using an ID-binding table.",
    "author": "SGC TECH AI",
    "license": "OPL-1",
    "depends": [
        "account",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/pgre_sync_views.xml",
        "views/menus.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}