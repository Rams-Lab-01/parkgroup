# -*- coding: utf-8 -*-
{
    'name': 'AML Compliance & goAML',
    'version': '19.0.1.0.2',
    'category': 'Compliance/AML',
    'summary': 'UAE Anti-Money Laundering Compliance with goAML Export',
    'description': """
AML Compliance & goAML Integration
====================================

End-to-end UAE AML compliance for Designated Non-Financial
Businesses and Professions (DNFBPs) in Real Estate.

Phase 1 — Risk Assessment Engine:
* Automated customer risk scoring (Low / Medium / High / Very High)
* FATF high-risk & monitored jurisdictions list
* PEP-aware risk escalation
* Configurable risk factors and weights
* Risk assessment linked to KYC applications and contacts
* Enhanced Due Diligence (EDD) trigger for high-risk customers
* Compliance officer review and override

Phase 2 — goAML XML Export:
* Suspicious Transaction Report (STR) generation
* Suspicious Activity Report (SAR) generation
* Cash Transaction Report (CTR) — AED 55,000 threshold
* goAML-compliant XML schema output
* Filing tracker with submission status

Phase 3 — Transaction Monitoring:
* Real-time transaction screening against risk profiles
* Threshold alerts for cash transactions
* Pattern detection for structuring

Phase 4 — Sanction List Screening:
* UN Consolidated Sanctions List
* UAE Local Terrorist List
* Automated screening on KYC submission

Phase 5 — Compliance Dashboard:
* MLRO reporting dashboard
* Overdue review tracking
* Filing status and audit trail

Phase 6 — Periodic Review Scheduler:
* Automated re-KYC scheduling based on risk level
* Expiry alerts for documents

Aligned with:
* UAE Federal Decree-Law No. 20 of 2018
* Cabinet Decision No. 10 of 2019
* FATF Recommendations
* goAML reporting standards
    """,
    'author': 'SGC TECH AI',
    'website_alt': 'https://www.scholarixglobal.com',
    'mobile': '+971-52-198-5231',
    'support': 'info@sgctech.ai',
    'website': 'https://www.sgctech.ai',
    'license': 'LGPL-3',
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
    'auto_install': False,
    'depends': [
        'base',
        'mail',
        'kyc_management',
        'account',
    ],
    'data': [
        # Security
        'security/aml_groups.xml',
        'security/ir.model.access.csv',
        'security/security.xml',

        # Data
        'data/opensanctions_config_data.xml',
        'data/sequence_data.xml',
        'data/sequence_phase2_data.xml',
        'data/edd_enquiry_data.xml',
        'data/risk_factor_data.xml',
        'data/fatf_jurisdiction_data.xml',
        'data/monitoring_rule_data.xml',
        'data/cron_data.xml',

        # Reports (must load before views that reference report action IDs)
        'reports/risk_assessment_report.xml',
        'reports/goaml_report_print.xml',
        'reports/screening_certificate.xml',
        'reports/consolidated_kyc_report.xml',

        # Views
        'views/risk_assessment_views.xml',
        'views/risk_factor_views.xml',
        'views/goaml_report_views.xml',
        'views/transaction_monitoring_views.xml',
        'views/sanctions_screening_views.xml',
        'views/opensanctions_views.xml',
        'views/dashboard_views.xml',
        'views/kyc_application_views.xml',
        'views/res_partner_views.xml',
        'views/edd_workflow_views.xml',
        'views/investigation_case_views.xml',
        'views/aml_menu.xml',

        # Wizard
        'wizard/risk_override_wizard_views.xml',
        'wizard/goaml_filing_wizard_views.xml',
    ],
}
