"""Owner decisions 26/10/2026 (evening), after the PGRE recheck - no money moves.

1. PBR I 1BR 408 (SC/2026/00288): the agreed price is PGRE's 1,855,179, not
   the workbook's discounted 1,511,739. Set it on the contract and the unit and
   replace the wrong "owed 176,473.27" flag in the contract notes.
2. Move 9 invoices back to the units PGRE books them on (link only):
     Miroslav Racek   INV/2026/00495-00498 -> Park Residency 317
                      INV/2026/00499-00502 -> Park Residency 318
     (were on Rana Arabi's contract SC/2026/00168, PBR II Studio 203)
     Nashwan Taalo    INV/2026/00244       -> Park Residency 505
     (was on Aldoobi's contract SC/2026/00200, PBR II Studio 410)
   Evidence: each invoice has the same name in PGRE, and its loan.line ->
   crm.lead -> property is the target unit (scripts/pgre_suspects.py and the
   recheck section of the README).  The target units have no contract in
   prod, so the link is the manual one (sold_id cleared, manual_property_id set).

Partner, amount, journal and reconciliation are not touched.

Run with:  odoo shell -d sgc_mt_parkgroup  < apply_408_price_and_relink.py
Set DRY_RUN = False to commit; with True everything is rolled back.
"""
DRY_RUN = True

PRICE_408 = 1855179.0
RELINK = {  # invoice name -> target unit name
    **{f'INV/2026/{n:05d} [PRES]': 'Park Residency - Studio 317' for n in (495, 496, 497, 498)},
    **{f'INV/2026/{n:05d} [PRES]': 'Park Residency - Studio 318' for n in (499, 500, 501, 502)},
    'INV/2026/00244 [PRES]': 'Park Residency - 1 Bedroom 505',
}
OLD_FLAG = '26/10/2026 - OVER-COLLECTION FLAGGED'
NOTE = (
    "26/10/2026 - PRICE CORRECTED TO 1,855,179 (owner decision, follows PGRE). "
    "This replaces the earlier over-collection flag, which was wrong. PGRE prices "
    "this unit at 1,855,179 with no discount (deal 1,935,386.16 = price + 4% DLD "
    "74,207.16 + 6,000), and the sales workbook computes its receivable, "
    "collection % and commission on the same figure. The buyer has paid "
    "1,953,938.12 in 12 receipts, including the 1,431,488.00 cash receipt of "
    "19/05/2025, so the unit is fully paid and 18,551.96 over. Of that, 9,177.00 "
    "(PBNK8/2025/00229, 02/01/2025) names Artem Tolmachev (PBR I 508 / 103) and "
    "probably belongs to him. In Odoo the last 9% of the plan and the DLD are not "
    "invoiced yet; the buyer's unapplied receipts cover them. No money moved."
)

Contract = env['sale.contract'].sudo()
Unit = env['property.details'].sudo()
Move = env['account.move'].sudo()


def show(tag):
    for name in ('SC/2026/00288', 'SC/2026/00168', 'SC/2026/00200'):
        c = Contract.search([('name', '=', name)])
        print(f"{tag} {c.name} {c.property_id.name}: price {c.sale_price:,.2f} paid {c.total_paid:,.2f} "
              f"fees {c.total_paid_fees:,.2f} balance {c.balance_due:,.2f} pct {c.collection_pct:.2f}")
    for uname in sorted(set(RELINK.values())) + ['Park Residency - 1 Bedroom 502']:
        u = Unit.search([('name', '=', uname)])
        inv = Move.search([('move_type', '=', 'out_invoice'), ('state', '=', 'posted'), ('property_id', '=', u.id)])
        settled = sum(inv.mapped('amount_total')) - sum(inv.mapped('amount_residual'))
        print(f"{tag} {uname}: {len(inv)} invoices, settled {settled:,.2f}")


show('BEFORE')

# 1. PBR I 408 price + flag
c408 = Contract.search([('name', '=', 'SC/2026/00288')])
assert len(c408) == 1 and abs(c408.sale_price - 1511739.0) < 0.01, c408.sale_price
notes = c408.notes or ''
if OLD_FLAG in notes:
    head, _sep, _tail = notes.partition(OLD_FLAG)
    notes = head.rstrip()
c408.write({'sale_price': PRICE_408, 'notes': (notes + '\n' + NOTE).strip()})
c408.property_id.write({'sale_price': PRICE_408})

# 2. relink, with an undo record printed to stdout
invs = Move.search([('name', 'in', list(RELINK)), ('move_type', '=', 'out_invoice'), ('state', '=', 'posted')])
assert len(invs) == len(RELINK), sorted(set(RELINK) - set(invs.mapped('name')))
print('UNDO,id,name,partner_id,sold_id,property_id,manual_property_id')
for inv in invs:
    print(f"UNDO,{inv.id},{inv.name},{inv.partner_id.id},{inv.sold_id.id or ''},"
          f"{inv.property_id.id or ''},{inv.manual_property_id.id or ''}")
for inv in invs:
    target = Unit.search([('name', '=', RELINK[inv.name])])
    assert len(target) == 1, RELINK[inv.name]
    inv.write({'sold_id': False, 'manual_property_id': target.id})

receipts = env['account.payment'].search([
    ('move_id.line_ids.matched_debit_ids.debit_move_id.move_id', 'in', invs.ids),
])
receipts._compute_property_attribution()

contracts = Contract.search([])
contracts._compute_total_paid()
contracts._compute_total_paid_fees()
env.flush_all()

show('AFTER ')
print("receipts re-attributed:", len(receipts), sorted(set(receipts.mapped('property_id.name'))))

if DRY_RUN:
    env.cr.rollback()
    print('DRY RUN - rolled back')
else:
    env.cr.commit()
    print('COMMITTED')
