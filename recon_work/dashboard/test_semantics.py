A = env['escrow.allocation'].sudo()
S = env['sale.contract'].sudo()
D = env['property.details'].sudo()
CO = [('company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 72); print(t); print('=' * 72)

pd = D.search([], limit=1)
pl = pd.get_development_kpis()

line('SECTION 7A - FIELD CONVENTION (from source docstring)')
print('  variance_amount = ALLOCATED - REQUIRED   (per field help text)')
print('    negative -> under-allocated | positive -> over-allocated')
print('  compute() confirms: variance = (allocated or 0) - required')
print('  no source data -> variance forced to 0.0')
print('')
print('  => CORRECT domains:')
print('     under-allocated : variance_amount < -0.01')
print('     over-allocated  : variance_amount >  0.01')

und = A.search(CO + [('variance_amount', '<', -0.01)])
ovr = A.search(CO + [('variance_amount', '>', 0.01)])
rec = A.search(CO + [('has_source_data', '=', True), ('variance_amount', '<=', 0.01), ('variance_amount', '>=', -0.01)])
awt = A.search(CO + [('has_source_data', '=', False)])
print('')
print('  actual counts with CORRECT semantics:')
print('    under-allocated (var < -0.01) = %d' % len(und))
print('    over-allocated  (var >  0.01) = %d' % len(ovr))
print('    reconciled                    = %d' % len(rec))
print('    awaiting source               = %d' % len(awt))
print('    all allocations               = %d' % A.search_count(CO))
print('')
print('  MY CURRENT (WRONG) DOMAINS:')
print('    viewUnderAllocated uses var > 0.01  -> %d records (these are OVER-allocated)' % A.search_count(CO + [('variance_amount', '>', 0.01)]))
print('    viewOverAllocated  uses var < -0.01 -> %d records (these are UNDER-allocated)' % A.search_count(CO + [('variance_amount', '<', -0.01)]))

print('')
print('  sanity: sum(allocated-required) over all = %s' % round(
    sum((r.allocated_amount or 0) - (r.required_amount or 0) for r in A.search(CO)), 2))
print('  cross-check: allocated - required = %s - %s = %s' % (
    pl['allocated_escrow'], pl['required_escrow'],
    round(pl['allocated_escrow'] - pl['required_escrow'], 2)))

line('SECTION 7B - recon_rate DENOMINATOR AMBIGUITY')
zero_req = A.search(CO + [('required_amount', '<=', 0)])
pos_req = A.search(CO + [('required_amount', '>', 0)])
print('  allocations with required <= 0 (no escrow rule) = %d' % len(zero_req))
print('  allocations with required >  0 (real rule)     = %d' % len(pos_req))
print('')
zr_rec = [r for r in zero_req if r.has_source_data and abs(r.variance_amount or 0) <= 0.01]
print('  of the no-requirement rows, counted as RECONCILED = %d' % len(zr_rec))
print('')
rate_all = len(rec) / len(A.search(CO)) * 100
pr_rec = [r for r in pos_req if r.has_source_data and abs(r.variance_amount or 0) <= 0.01]
rate_pos = (len(pr_rec) / len(pos_req) * 100) if pos_req else 0
print('  recon_rate over ALL allocations (what dashboard shows) = %.2f%%  (%d/%d)' % (
    rate_all, len(rec), len(A.search(CO))))
print('  recon_rate over allocations WITH a rule               = %.2f%%  (%d/%d)' % (
    rate_pos, len(pr_rec), len(pos_req)))
print('  => the published 70.8%% includes %d rows that have no escrow requirement' % len(zero_req))

line('SECTION 7C - the 17 "source but zero allocated" rows')
w = A.search(CO + [('has_source_data', '=', True), ('allocated_amount', '=', 0)])
print('  count = %d' % len(w))
for r in w:
    print('    id=%-5s required=%12.2f allocated=%12.2f variance=%12.2f' % (
        r.id, r.required_amount or 0, r.allocated_amount or 0, r.variance_amount or 0))

line('SECTION 7D - CORRECT CARD -> DRILL COUNTS (what the fix must produce)')
print('  Balance Due card 177,196,297.18 -> should open ALL outstanding contracts')
outst = S.search_count(CO + [('balance_due', '>', 0.01)])
print('     [balance_due > 0.01] = %d contracts, sum %s' % (
    outst, round(sum(r.balance_due or 0 for r in S.search(CO + [('balance_due', '>', 0.01)])), 2)))
print('  Aged >90 card 207 -> aged drill [balance_due>0.01, last_activity_date<=d90] = %d' % S.search_count(
    CO + [('balance_due', '>', 0.01), ('last_activity_date', '<=', (__import__('datetime').date.today() - __import__('datetime').timedelta(days=90)).isoformat())]))
print('  Expected Escrow card -> ALL allocations = %d' % A.search_count(CO))
print('  Allocated Escrow card -> allocations WITH source = %d' % A.search_count(CO + [('has_source_data', '=', True)]))
print('  Shortfall card -> UNDER-allocated = %d (var < -0.01)' % len(und))
print('  Recon Rate card -> reconciled = %d' % len(rec))
print('  Missing Source card -> awaiting = %d' % len(awt))

env.cr.rollback()
print(''); print('DONE (rolled back)')