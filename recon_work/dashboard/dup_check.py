from collections import defaultdict

I = env['sale.contract.installment'].sudo()
S = env['sale.contract'].sudo()
A = env['escrow.allocation'].sudo()
CO = [('company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 74); print(t); print('=' * 74)

line('DUPLICATE ANALYSIS: (contract_id, sequence) groups')

groups = defaultdict(list)
for i in I.search([('contract_id.company_id', 'in', env.companies.ids)]):
    groups[(i.contract_id.id, i.sequence)].append(i)

dups = {k: v for k, v in groups.items() if len(v) > 1}
print('  duplicate groups = %d' % len(dups))
print('  total installments in dup groups = %d' % sum(len(v) for v in dups.values()))

identical = diff_amount = diff_meta = 0
for k, v in dups.items():
    vals = set((i.amount or 0, i.percentage or 0, i.state, i.due_date or False) for i in v)
    if len(vals) == 1:
        identical += 1
    else:
        amounts = set((i.amount or 0) for i in v)
        if len(amounts) > 1:
            diff_amount += 1
        else:
            diff_meta += 1

print('  groups with IDENTICAL amount+pct+state+due : %d  <-- true duplicates' % identical)
print('  groups with DIFFERENT amounts             : %d' % diff_amount)
print('  groups same amount, different other cols  : %d' % diff_meta)

print('')
print('--- full schedules of the first 4 dup contracts ---')
for k, v in list(dups.items())[:4]:
    sc = S.browse(k[0])
    print('')
    print('  CONTRACT %s (id=%s) sale_price=%s' % (sc.name, sc.id, sc.sale_price))
    rows = I.search([('contract_id', '=', sc.id)], order='sequence, id')
    tot = 0.0
    for i in rows:
        tot += i.amount or 0
        print('    id=%-5s seq=%-3s name=%-28s pct=%-7s amount=%12.2f state=%-8s due=%-12s paid=%s' % (
            i.id, i.sequence, (i.name or '')[:28], i.percentage, i.amount or 0,
            i.state, i.due_date or '-', i.payment_date or '-'))
    print('    TOTAL schedule = %.2f  vs sale_price %.2f  (diff %.2f)' % (
        tot, sc.sale_price or 0, tot - (sc.sale_price or 0)))

line('HOW MANY CONTRACTS HAVE DUPLICATES?')
dup_contracts = set(k[0] for k in dups)
print('  distinct contracts affected = %d of %d sold' % (
    len(dup_contracts), S.search_count(CO + [('state', 'in', ('signed', 'completed'))])))
seqs = sorted(set(k[1] for k in dups))
print('  sequence numbers affected   = %s' % seqs)

line('DOES REMOVING DUPLICATES FIX THE SCHEDULE DRIFT?')
# for identical dup groups, deducting one copy should bring schedule closer to price
tot_dup_amount = sum((v[0].amount or 0) for k, v in dups.items()
                     if len(set((i.amount or 0) for i in v)) == 1)
print('  sum of one copy of each identical dup group = %.2f' % tot_dup_amount)
print('  (this is the amount that would be double-counted if left in place)')

line('ESCROW LINK INTEGRITY (correct fields: unit_id / contract_id / project_id)')
print('  allocations total             = %s' % A.search_count(CO))
print('  with unit_id                  = %s' % A.search_count(CO + [('unit_id', '!=', False)]))
print('  with contract_id              = %s' % A.search_count(CO + [('contract_id', '!=', False)]))
print('  with project_id               = %s' % A.search_count(CO + [('project_id', '!=', False)]))
print('  with NO unit_id               = %s' % A.search_count(CO + [('unit_id', '=', False)]))
noi = A.search(CO + [('unit_id', '=', False)])
for a in noi[:8]:
    print('     alloc %-5s project=%-14s required=%-12s allocated=%s' % (
        a.id, a.project_id.name or '-', a.required_amount or 0, a.allocated_amount or 0))

env.cr.rollback()
print(''); print('DONE (rolled back)')