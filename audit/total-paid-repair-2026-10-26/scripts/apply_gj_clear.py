"""Remove the false unit attribution from the 20 SETTLED GJ Properties invoices.

Why these 20 rows:
  They are the only GJ invoices whose money actually settled, so they are the
  only GJ rows that moved a unit's "Total Paid" above its selling price
  (Park Residency 412, PBR I 703, PBR I 702, PBR II 712, PBR II 713).

Evidence (PGRE pre-migration export, odoo_mcp/migration_out):
  * each of these 20 invoices carried NO unit in PGRE at all
    (property_id = False) - the unit pointer was added by the migration's
    amount-match fallback, not by a source document;
  * the escrow register (escrow_allocation) has no allocation for GJ;
  * the receipts that settled them are GJ's own money - PGRE memo on
    PBNK8/2026/00007: "Profit Share & TM received from GJ properties".

What this script does:
  * writes an undo CSV (id, old sold_id, old property_id, old manual link);
  * clears sold_id + manual_property_id on those 20 invoices.  property_id on
    account.move is computed from sold_id/tenancy_id, so it recomputes to
    empty by itself;
  * lets the receipt attribution recompute (the receipts that settled these
    invoices lose their derived unit as well);
  * recomputes Total Paid / fees on every contract.

Partner, amount, journal and the payment reconciliation are NOT touched: the
money stays in the ledger, only the false unit pointer goes.

Run with:  odoo shell -d sgc_mt_parkgroup  < apply_gj_clear.py
"""
import csv

GJ_SETTLED_INVOICE_IDS = [
    58437, 58438, 58439, 58440, 58441, 58442, 58443, 58444,
    58449, 58450, 58451, 58452, 58453,
    58456, 58458, 58460,
    58498, 58499,
    58501, 69833,
]

invs = env['account.move'].browse(GJ_SETTLED_INVOICE_IDS)

with open('/tmp/undo_gj_unit_links_2026-10-26.csv', 'w', newline='') as fh:
    w = csv.writer(fh)
    w.writerow(['id', 'name', 'partner_id', 'sold_id', 'property_id', 'manual_property_id'])
    for inv in invs:
        w.writerow([inv.id, inv.name, inv.partner_id.id, inv.sold_id.id or '',
                    inv.property_id.id or '', inv.manual_property_id.id or ''])

invs.write({'sold_id': False, 'manual_property_id': False})

# the receipts that settled those invoices lose the derived unit with them
receipts = env['account.payment'].search([
    ('move_id.line_ids.matched_debit_ids.credit_move_id.move_id', 'in', GJ_SETTLED_INVOICE_IDS),
    ('move_id.line_ids.matched_credit_ids.debit_move_id.move_id', 'in', GJ_SETTLED_INVOICE_IDS),
])
receipts._compute_property_attribution()

contracts = env['sale.contract'].sudo().search([])
contracts._compute_total_paid()
contracts._compute_total_paid_fees()

env.cr.commit()

print("GJ invoices unlinked:", len(GJ_SETTLED_INVOICE_IDS))
print("receipts recomputed:", len(receipts))
print("receipts still showing a unit:",
      env['account.payment'].search_count([('property_id', '!=', False),
                                           ('partner_id', '=', 1230)]))
for name in ('Park Residency - Studio 213', 'Park Residency - Studio 412',
             'Park Beach Residence I - Studio 703', 'Park Beach Residence I - 1 Bedroom 702',
             'Park Beach Residence I - 1 Bedroom 408', 'Park Beach Residence II - 1 Bedroom 712',
             'Park Beach Residence II - Studio 713', 'Park Beach Residence I - 1 Bedroom 108',
             'Park Beach Residence II - 1 Bedroom 106'):
    unit = env['property.details'].search([('name', '=', name)], limit=1)
    for c in env['sale.contract'].search([('property_id', '=', unit.id), ('state', '!=', 'cancelled')]):
        print(f"  {c.name} {name}: price {c.sale_price:,.2f} paid {c.total_paid:,.2f} "
              f"fees {c.total_paid_fees:,.2f} balance {c.balance_due:,.2f}")
