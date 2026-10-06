from collections import defaultdict

S = env['sale.contract'].sudo()
I = env['sale.contract.installment'].sudo()
CO = [('company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 72); print(t); print('=' * 72)

pd = env['property.details'].sudo().search([], limit=1)
pl = pd.get_development_kpis()

sold = S.search(CO + [('state', 'in', ('signed', 'completed'))])
print('sold contracts (signed/completed) = %d' % len(sold))

# gather installments grouped by contract
paid = defaultdict(float)
pend = defaultdict(float)
paid_cnt = defaultdict(int)
pend_cnt = defaultdict(int)
for inst in I.search([('contract_id.company_id', 'in', env.companies.ids)]):
    cid = inst.contract_id.id
    amt = inst.amount or 0.0
    if inst.state == 'paid':
        paid[cid] += amt; paid_cnt[cid] += 1
    else:
        pend[cid] += amt; pend_cnt[cid] += 1

line('SECTION 3A - WHICH DEFINITION DO THE CARD NUMBERS USE?')

sum_sale = 0.0
sum_total_paid = 0.0
sum_paid_inst = 0.0
sum_bal_field = 0.0
sum_pend = 0.0
for sc in sold:
    sum_sale += sc.sale_price or 0.0
    sum_total_paid += sc.total_paid or 0.0
    sum_paid_inst += paid.get(sc.id, 0.0)
    sum_bal_field += sc.balance_due or 0.0
    sum_pend += pend.get(sc.id, 0.0)

print('  A. sum(sale_price)                       = %15.2f' % sum_sale)
print('  B. sum(contract.total_paid field)        = %15.2f' % sum_total_paid)
print('  C. sum(paid installment.amount)          = %15.2f' % sum_paid_inst)
print('  D. sum(contract.balance_due field)       = %15.2f' % sum_bal_field)
print('  E. sum(pending installment.amount)       = %15.2f' % sum_pend)
print('')
print('  A - B  (total_paid basis)   = %15.2f   <- what the BALANCE DUE card computes' % (sum_sale - sum_total_paid))
print('  A - C  (paid-inst basis)    = %15.2f' % (sum_sale - sum_paid_inst))
print('  D      (balance_due field)  = %15.2f   <- what the drill-down filters on' % sum_bal_field)
print('  E      (schedule pending)   = %15.2f' % sum_pend)
print('')
print('  payload balance_due  = %s' % pl['balance_due'])
print('  payload collected    = %s' % pl['collected'])
print('  payload sales_value  = %s' % pl['sales_value'])
print('')
print('  MATCH A-B vs payload balance_due : %s' % ('YES' if abs((sum_sale - sum_total_paid) - pl['balance_due']) < 0.02 else 'NO'))
print('  MATCH C   vs payload collected   : %s' % ('YES' if abs(sum_paid_inst - pl['collected']) < 0.02 else 'NO'))
print('  MATCH A   vs payload sales_value : %s' % ('YES' if abs(sum_sale - pl['sales_value']) < 0.02 else 'NO'))

line('SECTION 3B - THE 3-WAY GAP (why 3 different balance numbers exist)')
print('  Card  (sale_price - total_paid)  = %15.2f' % (sum_sale - sum_total_paid))
print('  Field (sum of contract.balance_due)= %15.2f' % sum_bal_field)
print('  GAP card vs field                 = %15.2f' % (sum_bal_field - (sum_sale - sum_total_paid)))
print('  Schedule pending installments     = %15.2f' % sum_pend)
print('  GAP field vs schedule             = %15.2f' % (sum_bal_field - sum_pend))

print('')
print('  --- contracts where balance_due field != sale_price - total_paid ---')
bad = [sc for sc in sold if abs((sc.balance_due or 0.0) - ((sc.sale_price or 0.0) - (sc.total_paid or 0.0))) > 0.01]
print('  count = %d of %d' % (len(bad), len(sold)))
bad.sort(key=lambda s: -abs((s.balance_due or 0.0) - ((s.sale_price or 0.0) - (s.total_paid or 0.0))))
print('  %-14s %-12s %12s %12s %12s %12s' % ('contract', 'state', 'sale_price', 'total_paid', 'bal_field', 'dif'))
for sc in bad[:12]:
    d = (sc.balance_due or 0.0) - ((sc.sale_price or 0.0) - (sc.total_paid or 0.0))
    print('  %-14s %-12s %12.2f %12.2f %12.2f %12.2f' % (
        sc.name or sc.id, sc.state, sc.sale_price or 0, sc.total_paid or 0, sc.balance_due or 0, d))

print('')
print('  --- contracts where total_paid field != sum(paid installments) ---')
bad2 = [sc for sc in sold if abs((sc.total_paid or 0.0) - paid.get(sc.id, 0.0)) > 0.005]
print('  count = %d of %d' % (len(bad2), len(sold)))
bad2.sort(key=lambda s: -abs((s.total_paid or 0.0) - paid.get(s.id, 0.0)))
print('  %-14s %-12s %12s %12s %12s %12s' % ('contract', 'state', 'total_paid', 'sum_paid', 'paid_cnt', 'dif'))
for sc in bad2[:12]:
    d = (sc.total_paid or 0.0) - paid.get(sc.id, 0.0)
    print('  %-14s %-12s %12.2f %12.2f %12s %12.2f' % (
        sc.name or sc.id, sc.state, sc.total_paid or 0, paid.get(sc.id, 0.0), paid_cnt.get(sc.id, 0), d))

line('SECTION 3C - INSTALLMENT SCHEDULE vs CONTRACT PRICE')
mism = []
for sc in sold:
    sched = paid.get(sc.id, 0.0) + pend.get(sc.id, 0.0)
    if abs(sched - (sc.sale_price or 0.0)) > 0.01:
        mism.append((sc, sched, sched - (sc.sale_price or 0.0)))
print('  contracts where sum(schedule) != sale_price : %d of %d' % (len(mism), len(sold)))
mism.sort(key=lambda t: -abs(t[2]))
print('  %-14s %12s %12s %12s' % ('contract', 'sale_price', 'schedule', 'difference'))
for sc, sched, d in mism[:12]:
    print('  %-14s %12.2f %12.2f %12.2f' % (sc.name or sc.id, sc.sale_price or 0, sched, d))
if mism:
    print('  TOTAL schedule drift = %15.2f' % sum(d for _, _, d in mism))

line('SECTION 3D - INSTALLMENT DATA QUALITY')
print('  paid with NULL payment_date  : %s' % I.search_count(CO + [('state', '=', 'paid'), ('payment_date', '=', False)]))
print('  non-paid WITH payment_date   : %s' % I.search_count([('contract_id.company_id', 'in', env.companies.ids),
                                                                   ('state', '!=', 'paid'), ('payment_date', '!=', False)]))
print('  amount <= 0                  : %s' % I.search_count([('contract_id.company_id', 'in', env.companies.ids),
                                                                   ('amount', '<=', 0)]))
print('  NULL amount                  : %s' % I.search_count([('contract_id.company_id', 'in', env.companies.ids),
                                                                   ('amount', '=', False)]))
print('  installment states: %s' % I._read_group([('contract_id.company_id', 'in', env.companies.ids)], ['state'], ['__count']))

line('SECTION 3E - CONTRACT STATES vs SOLD UNITS')
print('  contract states: %s' % S._read_group(CO, ['state'], ['__count']))
print('  sold units (property.details) = %s ; sold contracts = %s' % (pl['sold_units'], len(sold)))

env.cr.rollback()
print(''); print('DONE (rolled back)')