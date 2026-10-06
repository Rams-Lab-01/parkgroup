# SGC - Offplan Rental

**Property Sale & Rental Management with Portal Syndication and Public Website**

![Version](https://img.shields.io/badge/version-19.0.1.0.0-blue)
![Odoo](https://img.shields.io/badge/Odoo-19.0-875A7B)
![License](https://img.shields.io/badge/license-OPL--1-green)

## Overview

SGC Offplan Rental combines four previously separate, code-dependent SGC modules
into one application: core property sale (with offplan-style installment payment
plans) and rental management, multi-portal listing syndication, and a public
rental website front-end. It gives real-estate teams a single place to manage the
full lifecycle of sale and rental properties — from listing and lead intake to
contracts, installment collection, and maintenance.

## Key Features

- **Property Sale & Rental Management** — unified management of sale and rental units.
- **Offplan Installment Payment Plans** — structured payment schedules for sale and rental contracts.
- **Lease Contract Management** — create and track lease agreements end to end.
- **Landlord & Customer Management** — maintain landlord, tenant, and buyer records.
- **Property Maintenance** — log and resolve maintenance requests against properties.
- **Customer Recurring Invoice** — automate recurring rental invoicing.
- **Flexible Payment Plans** — configurable schedules and milestones.
- **Multi-Portal Listing Syndication** — publish listings and capture leads across external portals.
- **Public Rental Website** — search, filtering, and inquiry capture for prospective tenants/buyers.

## Installation

1. Copy `sgc_offplan_rental_property_management` into your Odoo `addons` path.
2. Update the apps list (Apps > Update Apps List).
3. Install **SGC - Offplan Rental**.

The module depends on: `base`, `web`, `mail`, `contacts`, `account`, `hr`,
`maintenance`, `crm`, `website`, `website_mail`, `portal`.

## Configuration

1. Configure payment-schedule templates under the Offplan/Rental settings.
2. Set up portal connectors and XML feed configuration for listing syndication.
3. Publish properties to the public website via the property publish wizard.

## Usage

1. Create properties and assign sale or rental terms.
2. Generate installment payment plans for offplan sale/rental contracts.
3. Syndicate listings to configured portals and review incoming leads.
4. Manage lease contracts, recurring invoices, and maintenance from the property record.

## Technical Details

| | |
|---|---|
| **Module** | `sgc_offplan_rental_property_management` |
| **Version** | 19.0.1.0.0 |
| **Category** | Real Estate |
| **License** | OPL-1 |
| **Author** | SGC TECH AI |

## Support

- Website: https://sgctech.ai
- Support: bran@sgctech.ai
