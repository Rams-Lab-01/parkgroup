from collections import defaultdict

D = env['property.details'].sudo()
S = env['sale.contract'].sudo()
I = env['sale.contract.installment'].sudo()
A = env['escrow.allocation'].sudo()
R = env['escrow.release'].sudo()
CO = [('company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 74); print(t); print('=' * 74)

line('1. ACCOUNTING TABLES - is there any accounting data to collide with?')
for m in ('account.move', 'account.move.line', 'account.payment', 'account.journal'):
    print('  %-20s = %s' % (m, env[m].sudo().search_count([])))
print('  escrow.release       = %s' % R.search_count([]))

line('2. INSTALLMENT -> INVOICE LINKAGE (stale links would cause false matches)')
print('  installments with invoice_id set = %s' % I.search_count([('invoice_id', '!=', False)]))
print('  installment state distribution   = %s' % I._read_group(
    [('contract_id.company_id', 'in', env.companies.ids)], ['state'], ['__count']))
print('  invoice_id column all NULL       : %s' % (
    'YES - clean' if I.search_count([('invoice_id', '!=', False)]) == 0 else 'NO - stale links present'))

line('3. CONTRACT -> INVOICE LINKAGE')
print('  contracts with invoice_ids       = %s' % S.search_count(CO + [('invoice_ids', '!=', False)]))
print('  invoice_count > 0                = %s' % S.search_count(CO + [('invoice_count', '>', 0)]))
print('  overall_payment_state values     = %s' % S._read_group(CO, ['overall_payment_state'], ['__count']))
print('  total_paid > 0                   = %s' % S.search_count(CO + [('total_paid', '>', 0)]))

line('4. DUPLICATE / ORPHAN CHECKS on the reconciliation keys')
dups = defaultdict(list)
for i in I.search([('contract_id.company_id', 'in', env.companies.ids)]):
    dups[(i.contract_id.id, i.sequence)].append(i.id)
dd = {k: v for k, v in dups.items() if len(v) > 1}
print('  duplicate (contract_id, sequence) installment groups = %s' % len(dd))
for k, v in list(dd.items())[:10]:
    print('     contract=%s seq=%s ids=%s' % (k[0], k[1], v))

orph = I.search([('contract_id', '=', False)])
print('  installments with NO contract        = %s' % len(orph))
print('  allocations with NO unit link        = %s' % A.search_count(CO + [('property_id', '=', False)])
      if 'property_id' in A._fields else '  n/a')
print('  contracts with NO property_id        = %s' % S.search_count(CO + [('property_id', '=', False)]))
print('  contracts with NO payment_schedule   = %s' % S.search_count(CO + [('payment_schedule_id', '=', False)])
      if 'payment_schedule_id' in S._fields else '  n/a')

line('5. UNITS vs CONTRACTS consistency (sold unit must have a contract)')
sold_units = D.search(CO + [('state', 'in', ('sold', 'completed'))])
sold_unit_ids = set(sold_units.ids)
contracted = set(S.search(CO + [('state', 'in', ('signed', 'completed'))]).mapped('property_id').ids)
print('  units marked sold        = %s' % len(sold_unit_ids))
print('  units with a contract    = %s' % len(contracted))
print('  sold but NO contract     = %s' % len(sold_unit_ids - contracted))
print('  contracted but NOT sold  = %s' % len(contracted - sold_unit_ids))
onlysold = sold_unit_ids - contracted
onlycont = contracted - sold_unit_ids
for u in D.browse(sorted(onlysold))[:8]:
    print('     sold-no-contract : %s / %s' % (u.project_id.name, u.name))
for u in D.browse(sorted(onlycont))[:8]:
    print('     contract-not-sold: %s / %s' % (u.project_id.name, u.name))

line('6. ESCROW ALLOCATION -> UNIT link integrity')
if 'property_id' in A._fields:
    alloc_unit = set(A.search(CO).mapped('property_id').ids)
    print('  allocations linked to units = %s' % len(A.search(CO + [('property_id', '!=', False)])))
    print('  distinct units covered      = %s' % len(alloc_unit))
    print('  sold units WITHOUT allocation = %s' % len(sold_unit_ids - alloc_unit))
else:
    print('  escrow.allocation has no property_id field')
    print('  fields: %s' % [f for f in A._fields if 'unit' in f or 'propert' in f or 'contract' in f])

line('7. RECONCILIATION-READY CHECK')
print('  installment.invoice_id exists and is NULL everywhere : %s' % (
    'YES' if 'invoice_id' in I._fields and I.search_count([('invoice_id', '!=', False)]) == 0 else 'NO'))
print('  installment.due_date populated                      : %s/%s' % (
    I.search_count([('contract_id.company_id', 'in', env.companies.ids), ('due_date', '!=', False)]),
    I.search_count([('contract_id.company_id', 'in', env.companies.ids)])))
print('  installment.payment_date populated for paid         : %s/%s' % (
    I.search_count([('contract_id.company_id', 'in', env.companies.ids), ('state', '=', 'paid'), ('payment_date', '!=', False)]),
    I.search_count([('contract_id.company_id', 'in', env.companies.ids), ('state', '=', 'paid')])))

env.cr.rollback()
print(''); print('DONE (rolled back)')