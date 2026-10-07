SGC - Property Lead Journey
===========================

Single, governed CRM lead spine for property sales.

Why
---
The CRM pipeline and the property-management sale instruments were disjoint:
``sale.contract`` (the real sale document: EOI -> booked -> confirmed ->
spa_issued -> spa_signed) had **no** link back to the ``crm.lead``, and the
public website inquiry created a lead **without** ``property_id``. So a lead
could never be traced into the sale, and the pipeline could disagree with the
contract list.

What
----
* ``sale.contract.lead_id`` — the missing link, with smart buttons on the lead
  form (Contracts / EOIs / Bookings / SPAs) and a **Sale Journey** tab.
* **Automatic stage hand-off** — the contract is the system of record, so the
  CRM stage is derived from it:
    - EOI / booking / confirmation -> lead advances to the proposal stage;
    - SPA signed -> lead is **Won** (probability 100);
    - refund / cancel -> lead is re-opened to the proposal stage.
* The EOI and booking wizards carry the originating lead through to the
  contract (opened from a lead form, or pre-selected from the property).
* **Website intake fix** — the inquiry's ``crm.lead`` is created *with*
  ``property_id`` and the inquiry is back-linked (both directions).
* **Governed navigation** — the ``Leads`` menu now shows the whole pool (it was
  hard-wired to ``type='opportunity'``) and sales roles can see it, alongside a
  dedicated ``Opportunities`` entry.
* **Internal control** — ``journey_days_in_stage`` plus a daily SLA cron
  (``sgc_lead_journey.sla_days``, default 14) that schedules a visible to-do on
  the owner of any stalled open opportunity.

Design
------
Deliberately **additive**: it inherits — never rewrites — the property, EOI and
CRM models, so it can be installed/uninstalled without touching tenant data.
Stages are resolved **by name** (no hardcoded numeric ids), so the module is
portable across tenants.

Configuration
-------------
* ``sgc_lead_journey.sla_days`` — days a stage may sit before the SLA monitor
  flags it (default ``14``).

Testing
-------
Tests are tagged ``post_install`` (``-at_install``):
``odoo-bin -d <db> --test-enable --stop-after-init -i sgc_property_lead_journey``

License: LGPL-3.
