SGC PDC & Cheque Management (Odoo 19)
=====================================


Post-dated cheque register integrated with ``sgc_offplan_rental_property_management``.

* Receivable cheques (tenants / buyers) and payable cheques (landlords / vendors).
* Link a cheque to a sale installment, sale contract, tenancy, rent invoice, property and/or
  an accounting invoice. Smart buttons / "Register Cheque" actions on those forms.
* Workflow: Draft -> In Hand -> Deposited -> Cleared (or Bounced / Returned / Cancelled).
  Clearing posts the payment (registered against the linked invoice when set).
* Daily cron (``PDC: notify upcoming and matured cheques``): for cheques maturing within
  N days (default 7) and for matured-but-not-cleared cheques it posts an Odoo inbox
  notification, schedules a to-do activity and emails the responsible user (+ optional extra
  recipients). Each alert fires once per maturity date.
* Settings: PDC menu -> Settings. Groups: PDC User, PDC Manager.

Install: ``odoo -d <db> -i sgc_pdc_management --stop-after-init``; tests:
``odoo -d <test_db> -i sgc_pdc_management --test-tags /sgc_pdc_management --stop-after-init``.
