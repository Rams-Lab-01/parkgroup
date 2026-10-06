from collections import defaultdict

D = env['property.details'].sudo()
S = env['sale.contract'].sudo()
I = env['sale.contract.installment'].sudo()
A = env['escrow.allocation'].sudo()
AM = env['account.move'].sudo()
AML = env['account.move.line'].sudo()
AP = env['account.payment'].sudo()
CO = [('company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 74); print(t); print('=' * 74)

line('1b. WHAT ARE THE 3 EXISTING ACCOUNT.MOVE RECORDS?')
for mv in AM.search([]):
    print('  id=%-4s name=%-24s state=%-8s move_type=%-12s date=%s' % (
        mv.id, mv.name, mv.state, mv.move_type, mv.date))
print('')
print('  --- their lines ---')
for ln in AML.search([]):
    print('  move=%s line=%-4s account=%-28s debit=%-12s credit=%-12s partner=%s' % (
        ln.move_id.id, ln.id, (ln.account_id.code or ln.account_id.name or '?'),
        ln.debit, ln.credit, ln.partner_id.name or '-'))

line('2b. are any installments or contracts pointing at those moves?')
print('  installments with invoice_id set = %s' % I.search_count([('invoice_id', '!=', False)]))
print('  escrow.release rows              = %s' % env['escrow.release'].sudo().search_count([]))
print('  payments                         = %s' % AP.search_count([]))
mvids = AM.search([]).ids
orph = AML.search([('move_id', 'in', mvids)])
print('  moves referenced by escrow.release journal_entry_id = %s' % (
    env['escrow.release'].sudo().search_count([('journal_entry_id', 'in', mvids)])))

line('4. DUPLICATE / ORPHAN CHECKS on reconciliation keys')
dups = defaultdict(list)
for i in I.search([('contract_id.company_id', 'in', env.companies.ids)]):
    dups[(i.contract_id.id, i.sequence)].append(i.id)
dd = {k: v for k, v in dups.items() if len(v) > 1}
print('  duplicate (contract_id, sequence) groups = %s' % len(dd))
for k, v in list(dd.items())[:10]:
    print('     contract=%s seq=%s ids=%s' % (k[0], k[1], v))
print('  installments with NO contract   = %s' % I.search_count([('contract_id', '=', False)]))
print('  contracts with NO property_id   = %s' % S.search_count(CO + [('property_id', '=', False)]))
print('  allocations w/o unit link field : %s' % ('property_id' in A._fields))

line('5. UNITS vs CONTRACTS consistency')
sold_units = D.search(CO + [('state', 'in', ('sold', 'completed'))])
sold_unit_ids = set(sold_units.ids)
contracted = set(S.search(CO + [('state', 'in', ('signed', 'completed'))]).mapped('property_id').ids)
print('  units marked sold       = %s' % len(sold_unit_ids))
print('  units with a contract   = %s' % len(contracted))
onlysold = sold_unit_ids - contracted
onlycont = contracted - sold_unit_ids
print('  sold but NO contract    = %s' % len(onlysold))
print('  contracted but NOT sold = %s' % len(onlycont))
for u in D.browse(sorted(onlysold))[:10]:
    print('     sold-no-contract : %s / %s (state=%s)' % (u.project_id.name, u.name, u.state))
for u in D.browse(sorted(onlycont))[:10]:
    print('     contract-not-sold: %s / %s (state=%s)' % (u.project_id.name, u.name, u.state))

line('6. ESCROW ALLOCATION -> UNIT link integrity')
if 'property_id' in A._fields:
    alloc_unit = set(A.search(CO).mapped('property_id').ids)
    print('  allocations linked to a unit = %s' % A.search_count(CO + [('property_id', '!=', False)]))
    print('  distinct units covered       = %s' % len(alloc_unit))
    print('  sold units WITHOUT allocation= %s' % len(sold_unit_ids - alloc_unit))
else:
    print('  escrow.allocation link fields: %s' % [f for f in A._fields
          if 'unit' in f or 'propert' in f or 'contract' in f])

line('7. RECONCILIATION-READY SNAPSHOT')
tot_i = I.search_count([('contract_id.company_id', 'in', env.companies.ids)])
print('  installment.invoice_id all NULL         : %s' % (
    'YES' if I.search_count([('invoice_id', '!=', False)]) == 0 else 'NO'))
print('  due_date populated                      : %s/%s' % (
    I.search_count([('contract_id.company_id', 'in', env.companies.ids), ('due_date', '!=', False)]), tot_i))
print('  paid installments with payment_date     : %s/%s' % (
    I.search_count([('contract_id.company_id', 'in', env.companies.ids), ('state', '=', 'paid'), ('payment_date', '!=', False)]),
    I.search_count([('contract_id.company_id', 'in', env.companies.ids), ('state', '=', 'paid')])))
print('  contracts with total_paid > 0           : %s' % S.search_count(CO + [('total_paid', '>', 0)]))
print('  contracts with balance_due > 0          : %s' % S.search_count(CO + [('balance_due', '>', 0)]))
print('  escrow allocations                      : %s' % A.search_count(CO))

env.cr.rollback()
print(''); print('DONE (rolled back)')