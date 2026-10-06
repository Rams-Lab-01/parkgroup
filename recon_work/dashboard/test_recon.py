from datetime import timedelta, date

D = env['property.details'].sudo()
S = env['sale.contract'].sudo()
I = env['sale.contract.installment'].sudo()
A = env['escrow.allocation'].sudo()
P = env['property.project'].sudo()
CO = [('company_id', 'in', env.companies.ids)]

pd = D.search([], limit=1)
pl = pd.get_development_kpis()

d90 = date.today() - timedelta(days=90)
d90s = d90.isoformat()

def line(t):
    print('')
    print('=' * 72)
    print(t)
    print('=' * 72)

def chk(name, actual, expected, kind='eq'):
    if kind == 'eq':
        ok = abs(float(actual) - float(expected)) < 0.005 if isinstance(expected, float) else actual == expected
    elif kind == 'close':
        ok = abs(float(actual) - float(expected)) <= 0.05
    else:
        ok = True
    print('  %-34s got=%-22s want=%-22s %s' % (name, actual, expected, 'PASS' if ok else '*** MISMATCH ***'))
    return ok

results = []

line('SECTION 1 - CARD VALUE vs DRILL-DOWN DOMAIN (end-to-end reconciliation)')

print('')
print('--- Card 1: Total Units = %s ---' % pl['total_units'])
results.append(chk('Total Units drill []', D.search_count(CO), pl['total_units']))

print('')
print('--- Card 2: Sold Units = %s ---' % pl['sold_units'])
results.append(chk('Sold drill state in (sold,completed)',
                   D.search_count(CO + [('state', 'in', ('sold', 'completed'))]), pl['sold_units']))

print('')
print('--- Card 3: Available Units = %s ---' % pl['available_units'])
results.append(chk('Available drill state=available',
                   D.search_count(CO + [('state', '=', 'available')]), pl['available_units']))

print('')
print('--- Card 4: Sell-Through = %.2f%% ---' % pl['sell_through_pct'])
calc = (pl['sold_units'] / pl['total_units'] * 100.0) if pl['total_units'] else 0.0
results.append(chk('sell_through = sold/total', round(calc, 2), round(pl['sell_through_pct'], 2)))

print('')
print('--- Card 3b: does sold + available = total? (state vocabulary complete) ---')
states = D._read_group(CO, ['state'], ['__count'])
tot_from_states = sum(c for _, c in states)
for s, c in states:
    print('     state=%-14s count=%s' % (s, c))
results.append(chk('sum(all states)', tot_from_states, pl['total_units']))
print('     NOTE: sold+avail = %s ; total = %s ; other states = %s' % (
    pl['sold_units'] + pl['available_units'], pl['total_units'],
    tot_from_states - pl['sold_units'] - pl['available_units']))

print('')
print('--- Card 11: Aged >90 Days = %s ---' % pl['aged_overdue_units'])
aged_dom = [('company_id', 'in', env.companies.ids),
            ('balance_due', '>', 0.01),
            ('last_activity_date', '<=', d90s)]
aged_cnt = S.search_count(aged_dom)
results.append(chk('Aged drill count', aged_cnt, pl['aged_overdue_units']))
aged_sum = sum(r.balance_due or 0.0 for r in S.search(aged_dom))
results.append(chk('Aged drill sum', round(aged_sum, 2), round(pl['aged_overdue_amount'], 2), 'close'))

print('')
print('--- Card 18: Missing Source = %s ---' % pl['missing_source_count'])
results.append(chk('Awaiting-source drill has_source_data=False',
                   A.search_count(CO + [('has_source_data', '=', False)]), pl['missing_source_count']))

print('')
print('--- Card 17: Reconciliation Rate = %.2f%% ---' % pl['recon_rate'])
rec_cnt = A.search_count(CO + [('has_source_data', '=', True),
                               ('variance_amount', '<=', 0.01),
                               ('variance_amount', '>=', -0.01)])
all_cnt = A.search_count(CO)
calc = (rec_cnt / all_cnt * 100.0) if all_cnt else 0.0
results.append(chk('recon_rate = reconciled/all', round(calc, 2), round(pl['recon_rate'], 2)))
print('     reconciled=%s of total=%s' % (rec_cnt, all_cnt))

line('SECTION 1b - THE FOUR SUSPECT CARD/DRILL MISMATCHES')

print('')
print('--- Card 8: Balance Due shows %s but drills to viewAgedOverdue ---' % pl['balance_due'])
print('     displayed (all outstanding)      = %s' % pl['balance_due'])
print('     drill returns (aged >90 only)    = %s' % round(aged_sum, 2))
print('     GAP                              = %s' % round(pl['balance_due'] - aged_sum, 2))
all_bal = sum(r.balance_due or 0.0 for r in S.search(CO + [('balance_due', '>', 0.01)]))
not_aged = S.search_count(CO + [('balance_due', '>', 0.01), ('last_activity_date', '>', d90s)])
print('     all contracts balance_due>0.01   = %s over %s contracts' % (
    round(all_bal, 2), S.search_count(CO + [('balance_due', '>', 0.01)])))
print('     contracts NOT aged (<=90d active)= %s' % not_aged)

print('')
print('--- Card 13: Expected Escrow shows %s but drills to viewReconciled ---' % pl['required_escrow'])
rec_req = sum(r.required_amount or 0.0 for r in A.search(CO + [('has_source_data', '=', True),
                                                              ('variance_amount', '<=', 0.01),
                                                              ('variance_amount', '>=', -0.01)]))
req_all = sum(r.required_amount or 0.0 for r in A.search(CO))
print('     displayed (all allocations)      = %s' % round(req_all, 2))
print('     drill returns (reconciled only)  = %s' % round(rec_req, 2))
print('     GAP                              = %s' % round(req_all - rec_req, 2))

print('')
print('--- Card 14: Allocated Escrow shows %s but drills to viewUnderAllocated ---' % pl['allocated_escrow'])
und = A.search(CO + [('variance_amount', '>', 0.01)])
und_alloc = sum(r.allocated_amount or 0.0 for r in und)
alloc_all = sum(r.allocated_amount or 0.0 for r in A.search(CO))
print('     displayed (all allocations)      = %s' % round(alloc_all, 2))
print('     drill returns (under-allocated)  = %s over %s records' % (round(und_alloc, 2), len(und)))

print('')
print('--- Card 15: Escrow Shortfall shows %s but drills to viewOverAllocated ---' % pl['escrow_shortfall'])
ovr = A.search(CO + [('variance_amount', '<', -0.01)])
ovr_alloc = sum(r.allocated_amount or 0.0 for r in ovr)
ovr_req = sum(r.required_amount or 0.0 for r in ovr)
print('     displayed (required - allocated) = %s' % pl['escrow_shortfall'])
print('     drill returns (over-allocated)   = %s over %s records (variance=%s)' % (
    round(ovr_alloc - ovr_req, 2), len(ovr), round(sum(r.variance_amount or 0 for r in ovr), 2)))

line('SECTION 2 - AGING: does the drill-down miss NULL last_activity_date?')
null_la = S.search_count(CO + [('balance_due', '>', 0.01), ('last_activity_date', '=', False)])
print('  contracts balance_due>0.01 with NULL last_activity_date = %s' % null_la)
print('  server aging falls back to contract_date/today, drill-down uses <= d90')
if null_la:
    nb = sum(r.balance_due or 0.0 for r in S.search(CO + [('balance_due', '>', 0.01),
                                                           ('last_activity_date', '=', False)]))
    print('  balance_due excluded from aged drill by NULL activity = %s' % round(nb, 2))
    print('  *** GAP: aged drill excludes these contracts entirely ***')
else:
    print('  PASS no NULL last_activity_date among outstanding contracts')

env.cr.rollback()
print('')
print('SECTION1_PASS=%d FAIL=%d' % (sum(1 for r in results if r), sum(1 for r in results if not r)))
print('DONE (rolled back)')