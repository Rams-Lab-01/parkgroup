from collections import defaultdict

A = env['escrow.allocation'].sudo()
D = env['property.details'].sudo()
CO = [('company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 72); print(t); print('=' * 72)

pd = D.search([], limit=1)
pl = pd.get_development_kpis()

line('SECTION 6A - variance_amount INTEGRITY: field vs truth (required - allocated)')
rows = A.search(CO)
print('  total allocations = %d' % len(rows))

sign_flip = []
zero_wrong = []
rounded = []
for r in rows:
    req = r.required_amount or 0.0
    alc = r.allocated_amount or 0.0
    truth = req - alc
    var = r.variance_amount or 0.0
    if abs(var - truth) <= 0.01:
        continue
    if abs(var + truth) <= 0.01:
        sign_flip.append((r, truth, var))
    elif abs(var) <= 0.01:
        zero_wrong.append((r, truth, var))
    else:
        rounded.append((r, truth, var))

print('  sign-INVERTED rows (var == -(req-alc)) : %d' % len(sign_flip))
print('  var==0 but req!=alc (falsely settled)  : %d' % len(zero_wrong))
print('  other disagreements                    : %d' % len(rounded))

print('')
print('  --- sign-inverted detail ---')
print('  %-6s %14s %14s %14s %14s' % ('id', 'required', 'allocated', 'truth', 'field_var'))
for r, t, v in sign_flip[:25]:
    print('  %-6s %14.2f %14.2f %14.2f %14.2f' % (r.id, r.required_amount or 0, r.allocated_amount or 0, t, v))
print('  MISSED BY FIELD (true under-allocated, shown as negative): %s' % round(sum(t for _, t, _ in sign_flip if t > 0), 2))

print('')
print('  --- falsely-settled (var==0 but short) ---')
for r, t, v in zero_wrong:
    print('  %-6s req=%14.2f alloc=%14.2f truth=%14.2f field_var=%14.2f has_source=%s' % (
        r.id, r.required_amount or 0, r.allocated_amount or 0, t, v, r.has_source_data))

line('SECTION 6B - WHY THIS CORRUPTS THE PUBLISHED recon_rate')
true_rec = [r for r in rows if r.has_source_data and abs((r.required_amount or 0) - (r.allocated_amount or 0)) <= 0.01]
field_rec = [r for r in rows if r.has_source_data and abs(r.variance_amount or 0) <= 0.01]
false_rec = [r for r in field_rec if abs((r.required_amount or 0) - (r.allocated_amount or 0)) > 0.01]
missed_rec = [r for r in true_rec if abs(r.variance_amount or 0) > 0.01]

print('  field-based reconciled (what dashboard shows) = %d  -> rate %.2f%%' % (
    len(field_rec), len(field_rec) / len(rows) * 100))
print('  truth-based reconciled                        = %d  -> rate %.2f%%' % (
    len(true_rec), len(true_rec) / len(rows) * 100))
print('  FALSELY reconciled (variance==0 but short)    = %d' % len(false_rec))
for r in false_rec:
    print('      id=%s req=%.2f alloc=%.2f gap=%.2f  <-- counted as RECONCILED' % (
        r.id, r.required_amount or 0, r.allocated_amount or 0,
        (r.required_amount or 0) - (r.allocated_amount or 0)))
print('  MISSED reconciled (true settled, bad field)   = %d' % len(missed_rec))
print('  payload recon_rate = %s' % pl['recon_rate'])

line('SECTION 6C - DO THE DRILL-DOWNS RETURN THE RIGHT RECORDS?')
field_und = A.search(CO + [('variance_amount', '>', 0.01)])
field_ovr = A.search(CO + [('variance_amount', '<', -0.01)])
true_und = [r for r in rows if (r.required_amount or 0) - (r.allocated_amount or 0) > 0.01]
true_ovr = [r for r in rows if (r.required_amount or 0) - (r.allocated_amount or 0) < -0.01]

print('  UNDER-ALLOCATED')
print('    field drill (variance > 0.01)  = %d records, value %s' % (
    len(field_und), round(sum(r.required_amount or 0 for r in field_und), 2)))
print('    truth (req - alloc > 0.01)     = %d records' % len(true_und))
print('    truth records the field drill MISSES = %d' % len([r for r in true_und if r not in field_und]))
print('    truth total shortfall = %s' % round(sum((r.required_amount or 0) - (r.allocated_amount or 0) for r in true_und), 2))
print('')
print('  OVER-ALLOCATED')
print('    field drill (variance < -0.01) = %d records, variance sum %s' % (
    len(field_ovr), round(sum(r.variance_amount or 0 for r in field_ovr), 2)))
print('    truth (req - alloc < -0.01)    = %d records' % len(true_ovr))
print('    truth total over = %s' % round(sum((r.required_amount or 0) - (r.allocated_amount or 0) for r in true_ovr), 2))

print('')
print('  --- the 19 unaged contracts (balance due card gap) ---')
S = env['sale.contract'].sudo()
from datetime import timedelta, date
d90 = date.today() - timedelta(days=90)
notaged = S.search(CO + [('state', 'in', ('signed', 'completed')), ('balance_due', '>', 0.01),
                         ('last_activity_date', '>', d90.isoformat())])
print('    %d contracts, balance %s (card shows these but drill hides them)' % (
    len(notaged), round(sum(r.balance_due or 0 for r in notaged), 2)))
for r in notaged[:6]:
    print('      %-16s bal=%12.2f last_activity=%s' % (r.name, r.balance_due or 0, r.last_activity_date))

line('SECTION 6D - unit duplicates (correct field names)')
print('  property.details identity fields: %s' % [f for f in D._fields
      if f in ('unit_no', 'unit_number', 'name', 'unit_name', 'door_no', 'flat_no', 'code')])
idf = 'name' if 'name' in D._fields else None
print('  using identity field: %s' % idf)
dups = defaultdict(list)
for u in D.search(CO):
    key = (u.project_id.id if u.project_id else 0, (getattr(u, idf) or '').strip().lower())
    dups[key].append(u.id)
dd = {k: v for k, v in dups.items() if len(v) > 1}
print('  duplicate (project, name) groups: %s' % len(dd))
for k, v in list(dd.items())[:8]:
    print('     project=%s name=%r ids=%s' % (k[0], k[1], v))
uniq = set((u.project_id.id if u.project_id else 0, (getattr(u, idf) or '').strip().lower()) for u in D.search(CO))
print('  unique keys=%s vs units=%s' % (len(uniq), D.search_count(CO)))

env.cr.rollback()
print(''); print('DONE (rolled back)')