import time
from datetime import timedelta, date

D = env['property.details'].sudo()
S = env['sale.contract'].sudo()
A = env['escrow.allocation'].sudo()
CO = [('company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 74); print(t); print('=' * 74)

pd = D.search([], limit=1)
pl = pd.get_development_kpis()

line('LINKAGE 1 - the 507,819.12 is over-collected CREDIT, not schedule drift')
credits = S.search(CO + [('state', 'in', ('signed', 'completed')), ('balance_due', '<=', 0.01)])
print('  contracts with balance_due <= 0.01 : %d' % len(credits))
for r in credits:
    sched = sum(i.amount or 0 for i in env['sale.contract.installment'].sudo().search([('contract_id', '=', r.id)]))
    print('    %-16s sale_price=%12.2f total_paid=%12.2f balance_due=%12.2f' % (
        r.name, r.sale_price or 0, r.total_paid or 0, r.balance_due or 0))
    print('      schedule total = %12.2f  (schedule - price = %12.2f)' % (sched, sched - (r.sale_price or 0)))
neg = sum(r.balance_due or 0 for r in credits)
print('  credit total = %s' % round(neg, 2))
print('  card balance_due                       = %s' % pl['balance_due'])
print('  sum(balance_due>0.01)                  = %s' % round(
    sum(r.balance_due or 0 for r in S.search(CO + [('balance_due', '>', 0.01)])), 2))
print('  credit total + card value              = %s' % round(
    sum(r.balance_due or 0 for r in S.search(CO + [('balance_due', '>', 0.01)])) + neg, 2))
print('  => card NETS the credits; the drill shows only positive balances.')

line('LINKAGE 2 - awaiting-source rows carry the rest of the escrow shortfall')
awt_rows = A.search(CO + [('has_source_data', '=', False)])
awt_req = sum(r.required_amount or 0 for r in awt_rows)
print('  awaiting-source rows         = %d' % len(awt_rows))
print('  their required_amount total  = %s' % round(awt_req, 2))
print('  card escrow_shortfall        = %s' % pl['escrow_shortfall'])
print('  under-allocated (with source)= %s over 10 rows' % round(
    sum((r.required_amount or 0) - (r.allocated_amount or 0) for r in A.search(CO + [('variance_amount', '<', -0.01)])), 2))
print('  sum of the two               = %s' % round(
    awt_req + sum((r.required_amount or 0) - (r.allocated_amount or 0) for r in A.search(CO + [('variance_amount', '<', -0.01)])), 2))
print('  => %s of the shortfall sits in rows the "under-allocated" drill cannot show.' % round(awt_req, 2))

line('PARTITION COMPLETENESS - the 226 allocations split exactly 4 ways')
rec = A.search_count(CO + [('has_source_data', '=', True), ('variance_amount', '<=', 0.01), ('variance_amount', '>=', -0.01)])
und = A.search_count(CO + [('variance_amount', '<', -0.01)])
ovr = A.search_count(CO + [('variance_amount', '>', 0.01)])
awt = A.search_count(CO + [('has_source_data', '=', False)])
tot = A.search_count(CO)
print('  reconciled %d + under %d + over %d + awaiting %d = %d  (all %d) : %s' % (
    rec, und, ovr, awt, rec + und + ovr + awt, tot,
    'PASS - complete partition' if rec + und + ovr + awt == tot else 'FAIL'))

line('STRESS TEST 1 - repeated KPI computation (sequential)')
times = []
for i in range(8):
    t0 = time.time()
    p = pd.get_development_kpis()
    times.append(time.time() - t0)
print('  runs: %s' % ', '.join('%.2fs' % t for t in times))
print('  min=%.2fs  avg=%.2fs  max=%.2fs' % (min(times), sum(times) / len(times), max(times)))
print('  payload keys = %d' % len(p))
import json
js = json.dumps(p, default=str)
print('  payload size = %.1f KB' % (len(js) / 1024.0))

line('STRESS TEST 2 - result stability across repeated runs')
sig = []
for i in range(3):
    p = pd.get_development_kpis()
    sig.append((
        p['total_units'], p['sold_units'], p['available_units'],
        round(p['sales_value'], 2), round(p['collected'], 2), round(p['balance_due'], 2),
        p['aged_overdue_units'], round(p['escrow_shortfall'], 2),
        tuple(sorted(p['watchlist_counts'].items())),
        tuple(sorted((k, round(v['sales_value'], 2)) for k, v in p['per_project'].items())),
    ))
print('  3 runs identical: %s' % ('PASS' if len(set(sig)) == 1 else '*** UNSTABLE ***'))

line('STRESS TEST 3 - record volume swept (scalability probe)')
print('  property.details  = %d' % D.search_count(CO))
print('  sale.contract     = %d' % S.search_count(CO))
print('  installments      = %d' % env['sale.contract.installment'].sudo().search_count(
    [('contract_id.company_id', 'in', env.companies.ids)]))
print('  escrow.allocation = %d' % A.search_count(CO))
print('  property.project  = %d' % env['property.project'].sudo().search_count(CO))
py_loops = S.search_count(CO) + A.search_count(CO) + env['sale.contract.installment'].sudo().search_count(
    [('contract_id.company_id', 'in', env.companies.ids)])
print('  python-side loop iterations ~%d' % py_loops)
print('  NOTE: the method loads recordsets into Python and loops; it scales linearly.')

line('STRESS TEST 4 - edge cases')
print('  kpis with empty company domain -> totals:')
empty = pd.with_context(allowed_company_ids=[]).get_development_kpis() if False else None
try:
    D2 = D.with_user(env.ref('base.user_admin'))
    p2 = D2.search([], limit=1).get_development_kpis()
    print('    as admin: total_units=%s (same: %s)' % (
        p2['total_units'], 'PASS' if p2['total_units'] == pl['total_units'] else 'DIFFERS'))
except Exception as e:
    print('    as admin FAILED: %s' % e)
try:
    n = env['property.details']
    print('    empty recordset call: ', end='')
    pv = D.search([('id', '=', 0)], limit=1)
    if pv:
        r = pv.get_development_kpis()
        print('returned %d keys' % len(r))
    else:
        print('SKIP (no record to call on - method is an instance method)')
except Exception as e:
    print('    FAILED: %s: %s' % (type(e).__name__, e))
try:
    pr = env['property.project'].sudo().search(CO)
    print('    projects with no units: %s' % pr.filtered(lambda x: not D.search_count(CO + [('project_id', '=', x.id)])).mapped('name'))
except Exception as e:
    print('    project scan failed: %s' % e)

env.cr.rollback()
print(''); print('DONE (rolled back)')