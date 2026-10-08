# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author:  Mruthul Raj (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
################################################################################
{
    "name": "SGC - CRM Dashboard",
    'version': '19.0.1.5.0',
    "category": "Extra Tools",
    "summary": """Get a visual report of CRM through a Dashboard in CRM """,
    "description": """CRM dashboard module brings a multipurpose graphical
     dashboard for CRM module and making the relationship management 
     better and easier""",
    "author": "SmartClinic",
    "company": "SmartClinic",
    "maintainer": "SmartClinic",
    "website": "https://sgctech.ai",
    "depends": ["crm", "sale_management", "website"],
    "data": [
        "security/ir.model.access.csv",
        "data/mail_templates.xml",
        "data/crm_objection_data.xml",
        "views/crm_objection_views.xml",
        "views/crm_lead_views.xml",
        "views/crm_team_views.xml",
        "views/res_users_views.xml",
        "views/utm_campaign_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "sgc_crm_dashboard/static/src/css/dashboard.scss",
            "sgc_crm_dashboard/static/src/css/kpi.css",
            "sgc_crm_dashboard/static/src/js/dashboard/crm_dashboard.js",
            "sgc_crm_dashboard/static/src/xml/crm_dashboard.xml",
        ],
    },
    "images": [
        "static/description/icon.png",
        "static/description/banner.jpg",
    ],
    "license": "AGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
