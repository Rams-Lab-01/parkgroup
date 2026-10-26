# Total Paid repair — 2026-10-26

Production (`sgc_mt_parkgroup`, Odoo 19, container `sgc_rent_mt`).

## The complaint

"Total Paid" on a unit showed more than the unit's selling price, and did not
match the payment it was printed on. Park Residency 213 was the unit the owner
named; the same pattern was found on several other units.

## What Total Paid was calculating

`sale.contract.total_paid` (production code, `sgc_offplan_rental_property_management/models/core/sale_contract.py`):

```
_sgc_received_amount()
  -> sgc.eoi.receipt.helper._received_for_unit(unit)
     = SUM(account_payment.amount)          # FACE VALUE
       for every inbound receipt in state in_process/paid
       whose property_id == the unit
```

So it was **every receipt ever registered against the unit, at face value**:
money that never reached the unit's invoices, money that only partly reached
them, and fee money (DLD, admin, registration, Oqood, RAK) all counted in full.
The receipt report printed that same number as "Total paid to date", which is
why it never matched the receipt it was printed for.

## The fix (live)

Module `sgc_offplan_rental_property_management` 19.0.2.107 -> **19.0.2.110**:

1. **Total Paid = the cash settled on the unit's invoices**
   (`_sgc_settled_amount`): `SUM(amount_total - amount_residual)` over the
   unit's posted customer invoices. A unit with no invoice yet (an EOI-stage
   sale) falls back to the receipts, so the money gate still works.
2. **Fees broken out** in a new stored field `total_paid_fees` (DLD, admin,
   registration, Oqood, RAK). Total Paid still carries them - they are cash -
   but `balance_due` and `collection_pct` are computed net of fees, so a unit
   that is fully paid no longer reads as over-paid.
3. **No more staleness**: the daily cron ("Sales: Refresh Unit Payment
   Monitor" in production, "Property Management: Refresh Contract Collection
   Totals" in the repo) recomputes both. The stored total used to follow the
   payment *plan*, never the money.

## The data repair (live)

20 GJ Properties invoices carried a unit link they never had. PGRE (the
pre-migration source, `odoo_mcp/migration_out/invoices.csv`) records **no unit
on any of them**, the escrow register has **no allocation for GJ at all**, and
the receipts that settled them are GJ's own money - PGRE memo on
`PBNK8/2026/00007`: *"Profit Share & TM received from GJ properties"*.

Those 20 invoices (4.21M settled) were unlinked from the units; the money,
partner, journal and reconciliation were not touched.

| unit | before | after |
|---|---|---|
| Park Residency - Studio 412 | 933,082.64 (173% of price) | 108,078.54 (20%) |
| PBR I - Studio 703 | 1,326,255.45 | 452,756.06 (46%) |
| PBR I - 1 Bedroom 702 | 1,131,742.26 | 571,784.25 (45%) |
| PBR II - 1 Bedroom 712 | 2,122,575.49 | 1,296,378.00 (64%) |
| PBR II - Studio 713 | 596,197.21 | 426,569.92 (37%) |
| Park Residency - Studio 213 | 637,686.73 (122% of price) | 524,382.24 (100%) |

Undo: `evidence/undo_gj_unit_links_2026-10-26.csv` (id, old sold_id, old
property_id, old manual link).

## Still open

* **PBR I - 1 Bedroom 408** (`SC/2026/00288`) - the only unit still
  collecting more than its price (176,473.27 over). The owner's own reconciled
  workbook settles the direction: `data/PBR1 Sales.xlsx`, row for Unit 408 -
  **UNIT PRICE 1,855,179, DISCOUNT 18.51%, Discount Amount 343,440, Sold Value
  1,511,739** (= the Odoo price, so the price is right) and the plan was raised
  on the pre-discount 1,855,179 (it sums to 91% of it). So the invoices raised
  and the money taken are 176,473.27 above the agreed sold value: the buyer is
  owed that back, and the missing 9% of the plan must not be invoiced.
  **Owner decision 26/10/2026: flag only - no money movement.** The contract
  `notes` carry the flag; plan, invoices and receipts untouched.
  **Superseded by the PGRE recheck below - the 176,473.27 figure is not
  supported; the flag text needs correcting once the price is decided.**
* **Park Residency 213** - prod keeps price 524,382.24 and the live contract
  SC/2026/00500, so the unit stays 100% collected. **Owner decision
  26/10/2026.** The reconciled workbook row for this unit (a different buyer,
  sold value 569,991.56) is out of date for it.
* **Price cross-check against the reconciled workbook** (`evidence/price_crosscheck.csv`):
  272 of the 298 prod units carry exactly the workbook's sold value. Five
  differ, and they are price questions, not collection questions:

  | unit | prod price | workbook sold value | difference |
  |---|---|---|---|
  | PBR2 705 | 3,650,682.69 | 3,326,689.00 | prod higher by 323,993.69 |
  | PBR2 212 | 2,400,230.93 | 2,187,652.00 | prod higher by 212,578.93 |
  | PBR2 709 | 1,230,045.16 | 1,150,203.00 | prod higher by 79,842.16 |
  | PRY 213 | 524,382.24 | 569,991.56 | prod lower by 45,609.32 (decided: prod is right) |
  | PRY 310 | 562,271.23 | 567,950.73 | prod lower by 5,679.50 |

  Resolved by the PGRE recheck below: PRY 310 prod is right, the PBR2 three
  are unsold price edits, and the Park Golf Views units were checked against
  PGRE (12 match, 6 unsold ones differ).
* 67 **unsettled** GJ invoices still carry a false unit link. No money moves on
  them, but they inflate "invoiced" on those units.
* The unit-attribution sweep (`evidence/unit_attribution_plan.csv`, 8,876 rows)
  flags 13 invoices and 9 receipts whose PGRE unit is a *different* unit
  (re-point candidates) and 792 invoices / 304 receipts PGRE could not settle
  (review). None of them move a unit over its price today.

## Recheck against PGRE (pgre.odoo.com), 26/10/2026 evening

Read-only on both sides. Evidence in `evidence/pgre_recheck/`, scripts in
`scripts/` (`pgre_*.py`, `cmp_all.py`, `prod_*.sql`; `pgre_env.py` reads
`odoo_mcp/.env`). Prod container healthy after 2.110, no ERROR/Traceback in the
log since the restart; module at 19.0.2.110.

**Prices - every prod unit vs PGRE** (`cmp_all.csv`): 10 of 298 differ, and
**PBR I 408 is the only sold one**.

| unit | prod | PGRE | reading |
|---|---|---|---|
| PRY 213 | 524,382.24 | 524,382 | prod right. 569,991.56 is the old offer price on unpaid leads 388/399/468 |
| PRY 310 | 562,271.23 | 567,950.73 less 1% (5,679.50) = 562,271.23 | prod right. The workbook shows the price before discount |
| PBR2 212 / 705 / 709 | 2,400,230.93 / 3,650,682.69 / 1,230,045.16 | 2,187,630 / 3,326,646 / 1,118,633 | unsold on both sides; prod 9.7-10% higher, edited by admin 5/11/13 Oct with no tracking |
| PGV 401 / 402 / 403 | 1,319,084 / 1,374,093.60 / 1,410,108 | 1,293,717 / 1,348,069.10 / 1,386,606.20 | unsold; PGRE's 4th floor is a copy of its 3rd floor, prod keeps the floor ladder |
| PGV 404 / G01 / R01 | 838,475.75 / 4,914,080 / 4,500,000 | 821,364 / 4,668,376 / 4,615,222.50 | unsold; R01 has an EOI at 4.5M, no money |
| PGV other 12 | | | match to 0.40 |

**PBR I 408 - PGRE says the price is 1,855,179, not 1,511,739.** PGRE prices the
unit at 1,855,179 with no discount (deal 1,935,386.16 = price + 4% DLD 74,207.16
+ 6,000). The workbook's own Receivable (-24,552.83), % collection (105.16%)
and 8% commission (148,414.32) are also computed on 1,855,179; the discount
appears only in its Discount / Sold Value columns. The buyer's money is the
same in both systems: 12 receipts, **1,953,938.12**, including a 1,431,488.00
**cash** receipt dated 2025-05-19 that PGRE never applied (prod applied it to 42
invoices raised on 16 Oct, INV/2026/01448-01489). At 1,855,179 the unit is
fully paid and **18,551.96 over** (one 1% instalment). 9,177.00 of the money
(PBNK8/2025/00229, 2025-01-02) names **Artem Tolmachev**, the buyer of PBR I 508 and
103, so it probably belongs on his units. If the discount is real, the
buyer is owed **375,729.56**, not 176,473.27. Either way the current flag is
wrong. A cash receipt of this size should also be checked against the AML
cash-reporting threshold.

**Total Paid still above the money actually received on 7 units**
(`prod_decomp.csv`, checked unit by unit in PGRE with `pgre_suspects.py`):

| unit | prod Total Paid | PGRE receipts | over | cause |
|---|---|---|---|---|
| PBR2 1BR 712 (Forgerty) | 1,296,378.00 | 727,271.00 | 569,107.00 | migration entries (partner Marvic, 727,271 = PGRE) **and** 9 sync payments 569,107 both settle the invoices |
| PBR2 Studio 203 (Rana Arabi) | 1,009,765.89 | 446,942.70 | 562,823.19 | 8 invoices of **Miroslav Racek** (PGRE buyer of PRY 317/318) linked to this contract |
| PBR I 1BR 202 (Fady Karim) | 653,946.88 | 378,631.88 | 275,315.00 | entries (partner Nation Wide Excellency, 378,631.88 = PGRE) **and** own payments 275,315 |
| PBR2 Studio 107 | 464,337.86 | 411,065.70 | 53,272.16 | buyer entries 56,000 on top of payments |
| PBR2 Studio 410 (Aldoobi) | 414,814.20 | 375,808.20 | 39,006.00 | 1 invoice of **Nashwan Taalo** (PGRE buyer of PRY 502/505) |
| PBR I Studio 105 | 420,473.76 | 411,411.90 | 9,061.86 | entry 9,075.59 duplicates a receipt PGRE holds unapplied |
| PRY Studio 408 | 142,091.00 | 136,604.40 | 5,486.60 | buyer entry 5,486.60 on top of payments |

Total about 1.51M. The double-booked ones (712, 202, 107, 105, PRY 408) are the
9 Oct migration-entry / 13 Oct sync-payment duplicates from the 18 Oct JV
close-out, here applied to invoices on both sides.

**Sold in prod with no contract** (so no Total Paid anywhere): PRY 317 and 318
(Racek), 502 and 505 (Taalo), 311 and 416 (David Vobornik). PGRE has a live
SPA deal on each.

Cleared, not a problem: Abhinav (PBR I 208 / PBR2 614), Shimonov (PBR2 204 /
505), PBR I 708 and PBR2 309. Each matches PGRE. Invoices under a name variant
or family member (608, 314, 505, 603, 102/107, 309) are the known partner
mismatch the owner decided to leave.

### Applied on prod 26/10/2026 (owner decisions, no money moved)

`scripts/apply_408_price_and_relink.py`, dry-run (rolled back) first, then
committed. Undo: `evidence/undo_racek_taalo_links_2026-10-26.csv`.

* **PBR I 408** - price 1,855,179 on contract SC/2026/00288 and the unit (was
  1,511,739); the wrong "owed 176,473.27" flag replaced by the PGRE note.
  Odoo now reads 91% collected / balance 166,966.73, because the last 9% of the
  plan and the DLD are not invoiced in Odoo yet. The buyer's unapplied receipts
  cover both with 18,551.96 to spare. Raising those invoices and applying the
  receipts is money movement and was not done.
* **Relinked 9 invoices** (link only: sold_id cleared, manual_property_id set):
  Racek INV/2026/00495-00498 -> PRY 317, 00499-00502 -> PRY 318; Taalo
  INV/2026/00244 -> PRY 505. 5 receipts re-attributed with them.

| unit | Total Paid before | after | PGRE |
|---|---|---|---|
| PBR2 Studio 203 | 1,009,765.89 | 446,927.90 | 446,942.70 received |
| PBR2 Studio 410 | 414,814.20 | 375,808.20 | 375,808.20 received |
| PRY 317 (no contract) | 0 | 284,962.14 settled | 284,962.14 paid |
| PRY 318 (no contract) | 0 | 277,875.85 settled | 276,004.78 paid |
| PRY 505 (no contract) | 43,678.22 settled | 82,684.22 settled | |

**Still open after this:** the 5 double-booked units (PBR2 712 +569,107.00,
PBR I 202 +275,315.00, PBR2 107 +53,272.16, PBR I 105 +9,061.86, PRY 408
+5,486.60; about 912k), which need the duplicate removal from the 18 Oct JV close-out; the 6 sold
PRY units with no contract (317, 318, 502, 505, 311, 416); 408's
un-invoiced 9% + DLD; the 9,177 Tolmachev receipt on 408; the unsold PBR2 / PGV
price differences.

## Artefacts

Git holds this README, `deployed/` and the `scripts/*.py`. The repo's outbound
scan keeps raw data out of git, so the `evidence/` CSVs (customer amounts,
undo files) and every `.sql` stay only in the local working folder
`C:\Parkgroup Data\audit\total-paid-repair-2026-10-26\` and on the server under
`/root/deploy-backups/2026-10-26-total-paid/`.

* `evidence/verification.sql` - the after-state query (unit table + sweep).
* `evidence/before_sweep.sql` - the before-state query.
* `evidence/undo_gj_unit_links_2026-10-26.csv` - undo for the data repair.
* `scripts/match_units3.py` - the prod-vs-PGRE attribution matcher.
* `scripts/apply_gj_clear.py` - the script that unlinked the 20 invoices.

Server copies: `/root/deploy-backups/2026-10-26-total-paid/`
(pre-change module files in `A/`, evidence in `evidence/`).
