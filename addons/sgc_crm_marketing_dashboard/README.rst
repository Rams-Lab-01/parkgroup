SGC - CRM & Marketing Dashboard
===============================

One SGC-owned board answering three questions, live from real records:

1. **Potential buyers** — open opportunities, pipeline value, weighted
   (probability-adjusted) pipeline, win rate, new business in the period, the
   biggest live buyers, and the pipeline split by stage / source / owner, with
   ageing for SLA control.
2. **Campaigns** — per-campaign leads, opportunities, wins and attributed
   revenue.
3. **Marketing ROI** — spend, attributed revenue, ROAS, net, cost-per-lead and
   cost-per-acquisition.

Where
-----
``CRM -> CRM Dashboard`` (client action ``sgc_crm_marketing_dashboard``).
Enter campaign spend under ``CRM -> CRM Dashboard -> Campaign Spend``.

Attribution
-----------
Leads carry ``campaign_id`` / ``source_id`` / ``medium_id`` / ``expected_revenue``
(CRM standard). Revenue is attributed to a campaign through the property-sale
contract linked to the winning lead (``sale.contract.lead_id``, from
``sgc_property_lead_journey``). Campaign spend is captured on
``utm.campaign.marketing_cost`` (added here — Odoo has no cost field).

Scope
-----
CRM / marketing analytics. Complementary to the **property-operations**
dashboard in ``sgc_offplan_rental_property_management``
(``Property Management -> Statistics``), which covers inventory / sales /
collections / escrow. The two do not overlap.

Notes
-----
No hardcoded/placeholder data; stages resolved by name (portable across
tenants). ROAS/CPL/CPA show "—" until campaign spend is entered.

Testing
-------
``odoo-bin -d <db> --test-enable --stop-after-init -i sgc_crm_marketing_dashboard``

License: LGPL-3.
