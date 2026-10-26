"""Flag the PBR I 1BR 408 over-collection on the contract - no money moves.

Owner decision 2026-10-26: report it as a receivable owed to the buyer and
leave both the plan and the invoices alone for now.

Evidence (audit's price cross-check against the owner's reconciled workbook):
  data/PBR1 Sales.xlsx, Unit 408 -> UNIT PRICE 1,855,179, DISCOUNT 18.51%,
  Discount Amount 343,440, Sold Value 1,511,739 (= the Odoo sale price, so the
  price is right).  The instalment plan was raised on the pre-discount figure
  (it sums to 91% of 1,855,179), so the money collected is above the agreed
  sold value by the difference.

Run with:  odoo shell -d sgc_mt_parkgroup  < flag_408.py
"""
NOTE = (
    "26/10/2026 - OVER-COLLECTION FLAGGED (no money movement). "
    "Total Paid (cash settled on this unit's invoices) is 176,473.27 above the "
    "sale price of 1,511,739. Price is correct per the reconciled sales "
    "workbook (Unit 408: unit price 1,855,179, discount 18.51% = 343,440, "
    "sold value 1,511,739). The instalment plan and the invoices raised "
    "against it were built on the pre-discount 1,855,179, so the buyer is owed "
    "the difference and the un-invoiced 9% of the plan must not be billed. "
    "Owner decision 26/10/2026: flag only - plan, invoices and money left "
    "untouched until finance settles it with the buyer."
)

contract = env['sale.contract'].search([('name', '=', 'SC/2026/00288')], limit=1)
old = contract.notes or ''
if 'OVER-COLLECTION FLAGGED' not in old:
    contract.write({'notes': (old + '\n' + NOTE).strip()})
env.cr.commit()
print("flagged:", contract.name, "| total_paid", contract.total_paid,
      "| price", contract.sale_price, "| balance_due", contract.balance_due)
