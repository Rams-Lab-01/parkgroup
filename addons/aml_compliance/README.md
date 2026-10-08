# AML Compliance & goAML

UAE Anti-Money Laundering Compliance with goAML Export

## Description

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

## Module Information

| Field | Value |
|-------|-------|
| **Version** | 19.0.1.0.1 |
| **Category** | Compliance/AML |
| **Author** | SGC TECH AI |
| **License** | LGPL-3 |
- **Website:** https://www.sgctech.ai

## Dependencies

`base`, `mail`, `kyc_management`, `account`

## Installation

1. Copy this module to your Odoo addons directory.
2. Update the app list: **Settings → Apps → Update Apps List**
3. Search for **"AML Compliance & goAML"** and install.

## License

LGPL-3 — See [OCA license details](https://github.com/OCA/odoo-community.org/blob/master/website/Contribution/CONTRIBUTING.rst) for more information.
