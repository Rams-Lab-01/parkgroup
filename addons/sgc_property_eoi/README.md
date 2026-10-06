# sgc_property_eoi - EOI -> Booking -> Confirmed Sale

Extends `sgc_offplan_rental_property_management` (Odoo 19). Nothing in the base module is edited: every change is
an `_inherit` extension, so uninstalling or upgrading the base stays independent.

## Lifecycle

```
AVAILABLE --Register EOI--> EOI --Convert--> BOOKED --payment verified--> CONFIRMED SALE --handover--> SOLD
    ^   <--cancel/expire--+     (booking cancel -> AVAILABLE)                  |
    +------------ "Cancel Confirmed Sale" (manager, reason, audited) -----------+
```

| Stage | Unit (`property.details.state`) | Contract (`sale.contract.state`) | Record |
|---|---|---|---|
| Expression of interest | `eoi` | `eoi` | `property.eoi` (active) |
| Booking | `booked` | `booked` | `property.vendor` (confirmed) |
| Confirmed sale | `confirmed_sale` | `confirmed` -> `spa_issued` -> `signed` (SPA Signed) | booking `sale_confirmed` |
| Handover | `sold` | `completed` | - |
| Cancelled | back to `available` | `cancelled` | EOI / booking cancelled |

Unit status and contract status are separate fields; a unit stays `confirmed_sale` while its SPA is issued and
signed. Legacy keys (`available/booked/sold/rented/maintenance`, `draft/signed/completed/cancelled`) are all kept.

## Rules enforced in code
1. An EOI is a temporary reservation, not a booking; one active EOI per unit (partial unique index).
2. EOI cancel / expiry releases the unit - only if the unit is still held by that EOI.
3. A converted EOI cannot be cancelled; cancel its booking. A booking held on an EOI-reserved unit cannot release it.
4. Booking needs `booking_amount` (default = unit price x `booking_percentage`).
5. Confirmed Sale requires the booking payment to be **verified from real, posted inbound `account.payment` records**
   (states from `sgc_eoi.payment_verified_states`, default `in_process,paid`). The base flags
   `payment_recorded/payment_amount/payment_date` are now a derived reflection, so ticking them by hand no longer
   passes the gate. The base hard/permissive gate parameter (`sgc_mt.confirm_sales_requires_payment`) is honoured.
6. A Confirmed/Sold unit can only be released through `Cancel Confirmed Sale` (Property Manager, mandatory reason,
   audit event, payments untouched - refunds are an Accounting decision). Direct `write` of the unit state,
   `booking.action_cancel` and `contract.action_cancel` are all blocked.
7. State transitions on the unit are guarded in `property.details.write`.

## Payments
No parallel payment system. EOI and booking "Record Payment" wizards create and post a real `account.payment`
(inbound, customer) and link it (many2many). EOI payments carry over to the booking on conversion - no duplicate
payment, no duplicate contract (the EOI contract moves to `booked`).

## Security
- `property.eoi`: officer r/w/c, manager + unlink; multi-company rule.
- Property team gets **read-only** access to `account.payment` restricted by rule to payments linked to an EOI or
  booking (inverse fields `sgc_eoi_ids`, `sgc_booking_ids`) - not the payment ledger. Payments are created with
  `sudo()` only inside the wizards, after the amount/journal checks.
- Cancelling a confirmed sale: manager only. Draft EOIs only can be deleted.

## Migration
`post_init_hook`: nothing is converted or deleted. Existing units/contracts keep their state. Bookings with a manual
payment flag and no accounting payment are flagged `legacy_payment` (still pass the gate, labelled as legacy).

## Documents
`EXPRESSION OF INTEREST` and `PROPERTY BOOKING CONFIRMATION` share one design system (`report/dx_styles.xml`).
All wording (notice, terms, steps, documents, footer, validity days) is configurable per company
(Settings > Companies > "EOI / Booking Documents"); defaults are in `models/res_company.py`. No project, unit,
customer or currency is hard-coded.

## Known limits / follow-ups
- Dashboard KPIs keep their meaning; `get_property_stats` gains `eoi_property`, `confirmed_sale_property`.
  `get_development_kpis` still counts only `sold/completed` units as sold.
- Portfolio / project summary reports show `eoi` / `confirmed_sale` units without a dedicated badge.
- The base `selection` is re-declared (Odoo logs an "overrides existing selection" warning by design).
