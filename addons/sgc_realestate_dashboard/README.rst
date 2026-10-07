SGC - Real Estate Dashboard
===========================

A purpose-built, **SGC-owned** real-estate dashboard for the property-sale
journey. It replaces the generic, foreign (Cybrosys-fingerprinted) CRM
dashboard that the multi-tenant audit quarantined
(``sgc_realestate_brokerage_template`` ``excludes`` -> ``sgc_crm_dashboard``).

Every figure is aggregated **live** from real records — no hardcoded or
placeholder data — and every card/chart is clickable and opens the exact record
list behind the number.

Panels
------
* **Inventory** — ``property.details`` by state (available / booked / sold / total)
* **Sales & Collections (AED)** — sales value, collected, outstanding, escrow funded %
  (``sale.contract`` + ``sale.contract.installment`` + ``escrow.allocation``)
* **Customer Journey Funnel** — leads -> opportunities -> EOI -> booking -> SPA
* **Pipeline Aging** — open opportunities by days-in-stage (SLA control)
* **Inventory by Project** and **Leads by Source**

Where to find it
----------------
``Property Management -> Dashboard`` (client action ``sgc_realestate_dashboard``),
plus ``Property Management -> Dashboard -> Sales Analytics`` (native
graph/pivot/list drill-downs).

Design
------
Stages are resolved **by name** (no hardcoded numeric stage ids), so the module
is portable across tenants. The server model is ``sgc.realestate.dashboard``
(``get_dashboard_data`` / ``open_records``).

Dependencies
------------
``crm``, ``sale_management``, ``sgc_offplan_rental_property_management``,
``sgc_property_eoi_workflow``, ``sgc_escrow``, ``sgc_property_lead_journey``.

Testing
-------
``odoo-bin -d <db> --test-enable --stop-after-init -i sgc_realestate_dashboard``

License: LGPL-3.
