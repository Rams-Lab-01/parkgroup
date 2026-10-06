from collections import defaultdict

S = env['sale.contract'].sudo()
I = env['sale.contract.installment'].sudo()
A = env['escrow.allocation'].sudo()
D = env['property.details'].sudo()
P = env['property.project'].sudo()
CO = [('company_id', 'in', env.companies.ids)]
ICO = [('contract_id.company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 72); print(t); print('=' * 72)

line('SECTION 3D - INSTALLMENT DATA QUALITY (fixed domain)')
print('  installment fields with company: %s' % [f for f in I._fields if 'company' in f])
print('  total installments (all)          : %s' % I.search_count([]))
print('  total installments (our contracts): %s' % I.search_count(ICO))
print('  paid with NULL payment_date       : %s' % I.search_count(ICO + [('state', '=', 'paid'), ('payment_date', '=', False)]))
print('  non-paid WITH a payment_date      : %s' % I.search_count(ICO + [('state', '!=', 'paid'), ('payment_date', '!=', False)]))
print('  amount <= 0                       : %s' % I.search_count(ICO + [('amount', '<=', 0)]))
print('  NULL amount                       : %s' % I.search_count(ICO + [('amount', '=', False)]))
print('  NULL due_date                     : %s' % I.search_count(ICO + [('due_date', '=', False)]))
print('  states                            : %s' % I._read_group(ICO, ['state'], ['__count']))
neg = I.search(ICO + [('amount', '<', 0)])
print('  negative-amount installments      : %s (sum %s)' % (
    len(neg), round(sum(x.amount or 0 for x in neg), 2)))
print('  contracts with ZERO installments  : %s' % S.search_count(CO + [('state', 'in', ('signed', 'completed'))]))

line('SECTION 3E - CONTRACT STATES & ORPHANS')
print('  contract states: %s' % S._read_group(CO, ['state'], ['__count']))
sold = S.search(CO + [('state', 'in', ('signed', 'completed'))])
print('  sold contracts = %s' % len(sold))
noproj = [sc for sc in sold if not sc.property_id]
print('  sold contracts with NO property_id : %s' % len(noproj))
noproj2 = [sc for sc in sold if sc.property_id and not sc.property_id.project_id]
print('  sold contracts whose unit has NO project: %s' % len(noproj2))
print('  sale_price <= 0 among sold        : %s' % S.search_count(CO + [('state', 'in', ('signed', 'completed')), ('sale_price', '<=', 0)]))
print('  sale_price NULL among sold        : %s' % S.search_count(CO + [('state', 'in', ('signed', 'completed')), ('sale_price', '=', False)]))

line('SECTION 4A - ESCROW: variance vs required-allocated')
tot = A.search(CO)
print('  allocations total = %s' % len(tot))
nulldiff = 0
bigdiff = []
for r in tot:
    req = r.required_amount or 0.0
    alc = r.allocated_amount or 0.0
    var = r.variance_amount or 0.0
    if r.variance_amount is False or r.variance_amount is None:
        nulldiff += 1
        continue
    if abs(var - (req - alc)) > 0.01:
        bigdiff.append((r, var - (req - alc)))
print('  variance_amount NULL             = %s' % nulldiff)
print('  variance != required - allocated = %s' % len(bigdiff))
bigdiff.sort(key=lambda t: -abs(t[1]))
print('  %-22s %12s %12s %12s %12s' % ('allocation', 'required', 'allocated', 'variance', 'diff'))
for r, d in bigdiff[:10]:
    print('  %-22s %12.2f %12.2f %12.2f %12.2f' % (
        str(r.id), r.required_amount or 0, r.allocated_amount or 0, r.variance_amount or 0, d))
if bigdiff:
    print('  TOTAL unexplained variance drift = %s' % round(sum(d for _, d in bigdiff), 2))

line('SECTION 4B - ESCROW: NULLs and zero rows')
print('  required_amount NULL/0 : %s / %s' % (
    A.search_count(CO + [('required_amount', '=', False)]),
    A.search_count(CO + [('required_amount', '=', 0)])))
print('  allocated_amount NULL/0: %s / %s' % (
    A.search_count(CO + [('allocated_amount', '=', False)]),
    A.search_count(CO + [('allocated_amount', '=', 0)])))
print('  has_source_data TRUE/FALSE: %s / %s' % (
    A.search_count(CO + [('has_source_data', '=', True)]),
    A.search_count(CO + [('has_source_data', '=', False)])))
print('  with source but zero allocated: %s' % A.search_count(
    CO + [('has_source_data', '=', True), ('allocated_amount', '=', 0)]))
print('  without source but allocated>0: %s' % A.search_count(
    CO + [('has_source_data', '=', False), ('allocated_amount', '>', 0)]))
print('  all allocations with no project: %s' % A.search_count(CO + [('project_id', '=', False)]))

line('SECTION 4C - ESCROW PER PROJECT (blocking the "gap" claim)')
projs = P.search(CO)
gt_req = gt_alc = 0.0
for pr in projs:
    rows = A.search(CO + [('project_id', '=', pr.id)])
    req = sum(r.required_amount or 0 for r in rows)
    alc = sum(r.allocated_amount or 0 for r in rows)
    gt_req += req; gt_alc += alc
    print('  %-24s allocs=%-4s required=%14.2f allocated=%14.2f variance=%14.2f' % (
        pr.name, len(rows), req, alc, req - alc))
print('  %-24s allocs=%-4s required=%14.2f allocated=%14.2f variance=%14.2f' % (
    'TOTAL', len(tot), gt_req, gt_alc, gt_req - gt_alc))
print('  unassigned to a project = %s' % A.search_count(CO + [('project_id', '=', False)]))

line('SECTION 5 - UNIT / PROJECT DATA QUALITY')
print('  units with NULL area        : %s' % D.search_count(CO + [('area', '=', False)]))
print('  units with area <= 0        : %s' % D.search_count(CO + [('area', '<=', 0)]))
print('  units with NULL unit_type   : %s' % D.search_count(CO + [('unit_type', '=', False)]))
print('  units with NULL project     : %s' % D.search_count(CO + [('project_id', '=', False)]))
print('  units with NULL state       : %s' % D.search_count(CO + [('state', '=', False)]))
print('  projects with NULL/0 latlon : %s' % P.search_count(CO + ['|', ('geo_latitude', '=', False), ('geo_latitude', '=', 0)]))
print('  projects with NULL city     : %s' % P.search_count(CO + [('city', '=', False)]))
print('  projects with NULL code     : %s' % P.search_count(CO + [('code', '=', False)]))
dups = defaultdict(list)
for u in D.search(CO):
    key = (u.project_id.id if u.project_id else 0, (u.unit_no or u.name or '').strip().lower())
    dups[key].append(u.id)
d = {k: v for k, v in dups.items() if len(v) > 1}
print('  duplicate (project,unit_no) : %s' % len(d))
for k, v in list(d.items())[:8]:
    print('     project=%s unit=%r ids=%s' % (k[0], k[1], v))

env.cr.rollback()
print(''); print('DONE (rolled back)')