# -*- coding: utf-8 -*-
{
    'name': 'Park Group - EOI & Reservation Management',
    'version': '19.0.1.0.9',
    'category': 'Real Estate',
    'summary': 'Expression of Interest (EOI), refundable reservation workflow, contract stage pipeline and luxury QWeb agreements',
    'description': """Park Group Real Estate - EOI & Booking Extension
=================================================
This module introduces the preliminary Expression of Interest (EOI) stage into the property lifecycle:
* Property Stages: Available -> EOI -> Booked -> Sold
* Contract Stages: EOI -> Booked -> Confirmed -> SPA Issued -> SPA Signed (with Cancelled / Refunded)
* EOI Smart Buttons & automated unit-to-contract stage synchronization
* Refundable EOI deposit tracking with payment mode (Cheques, PDC, Cards, Wire, Cash)
* Money gate: the unit only enters EOI / Booked, and the sale only confirms, once a
  POSTED customer receipt exists in Accounting and is registered against the unit.
  The EOI, booking and booking-payment wizards post that receipt (or link one that
  is already posted); no parallel flag-only payment system.
* Conversion wizard from EOI to formal Booking upon receiving booking deposit
* Two luxury UAE QWeb PDF agreements:
  1. Expression of Interest "EOI" Agreement (Seller & Joint Purchaser particulars, unit specifications, legal terms & signature blocks)
  2. Reservation Form (Comprehensive developer booking contract with payment schedule and legal terms)
    """,
    'author': 'Park Group / SGC Tech AI',
    'website': 'https://parkgroup.sgctech.ai',
    'license': 'OPL-1',
    'depends': [
        'base',
        'mail',
        'contacts',
        'website',
        'sgc_offplan_rental_property_management',
        'sgc_unit_link',  # registers a standalone receipt against a unit
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/mail_template_spa.xml',
        'views/portal_spa_sign_templates.xml',
        'report/report_actions.xml',
        'report/spa_signature_report.xml',
        'report/eoi_agreement_template.xml',
        'report/reservation_form_template.xml',
        'wizard/eoi_wizard_views.xml',
        'views/property_details_views.xml',
        'views/sale_contract_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
