from collections import defaultdict

I = env['sale.contract.installment'].sudo()
S = env['sale.contract'].sudo()
CO = [('company_id', 'in', env.companies.ids)]
ICO = [('contract_id.company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 74); print(t); print('=' * 74)

line('INSTALLMENT LINE TAXONOMY - summary lines vs milestone lines')

summary_c = I.search(ICO + [('name', 'ilike', 'Collected to date%')])
summary_o = I.search(ICO + [('name', 'ilike', 'Outstanding balance%')])
print('  "Collected to date*" lines   = %s' % len(summary_c))
print('  "Outstanding balance*" lines = %s' % len(summary_o))

print('')
print('  --- full names (untruncated) ---')
seen = set()
for i in I.search(ICO + ['|', ('name', 'ilike', 'Collected to date%'),
                              ('name', 'ilike', 'Outstanding balance%')]):
    if i.name not in seen:
        seen.add(i.name)
        print('    %r' % i.name)

print('')
print('  states of summary lines:')
print('    collected-to-date : %s' % I._read_group([('name', 'ilike', 'Collected to date%')], ['state'], ['__count']))
print('    outstanding       : %s' % I._read_group([('name', 'ilike', 'Outstanding balance%')], ['state'], ['__count']))

scon = set(summary_c.mapped('contract_id').ids)
print('')
print('  distinct contracts with summary lines = %d' % len(scon))

line('DO THE 55 SUMMARY PAIRS SUM TO SALE PRICE?')
bad = []
tot_c = tot_o = 0.0
for cid in scon:
    sc = S.browse(cid)
    c = sum(i.amount or 0 for i in I.search([('contract_id', '=', cid), ('name', 'ilike', 'Collected to date%')]))
    o = sum(i.amount or 0 for i in I.search([('contract_id', '=', cid), ('name', 'ilike', 'Outstanding balance%')]))
    tot_c += c; tot_o += o
    if abs((c + o) - (sc.sale_price or 0)) > 0.01:
        bad.append((sc, c, o, c + o - (sc.sale_price or 0)))
print('  contracts checked          = %d' % len(scon))
print('  sum(collected-to-date)     = %.2f' % tot_c)
print('  sum(outstanding)           = %.2f' % tot_o)
print('  sum(c) + sum(o)            = %.2f' % (tot_c + tot_o))
print('  pairs NOT equal to price   = %d' % len(bad))
for sc, c, o, d in bad[:10]:
    print('     %-16s price=%12.2f c=%12.2f o=%12.2f diff=%12.2f' % (sc.name, sc.sale_price or 0, c, o, d))

line('LINE-LEVEL BREAKDOWN OF ALL 781 INSTALLMENTS')
def cnt(dom):
    return I.search_count(ICO + dom)
cats = {
    'summary collected (paid)'      : cnt([('name', 'ilike', 'Collected to date%')]),
    'summary outstanding (pending)' : cnt([('name', 'ilike', 'Outstanding balance%')]),
    'milestone paid'                : cnt([('state', '=', 'paid'), ('name', 'not ilike', 'Collected to date%')]),
    'milestone pending'             : cnt([('state', '=', 'pending'), ('name', 'not ilike', 'Outstanding balance%')]),
}
for k, v in cats.items():
    print('  %-32s = %s' % (k, v))
print('  %-32s = %s' % ('TOTAL', sum(cats.values())))

line('DATE COVERAGE BY LINE TYPE (what blocks reconciliation)')
def withdate(dom, f):
    return I.search_count(ICO + dom + [(f, '!=', False)]), I.search_count(ICO + dom)
for label, dom in [
    ('summary collected', [('name', 'ilike', 'Collected to date%')]),
    ('summary outstanding', [('name', 'ilike', 'Outstanding balance%')]),
    ('milestone paid', [('state', '=', 'paid'), ('name', 'not ilike', 'Collected to date%')]),
    ('milestone pending', [('state', '=', 'pending'), ('name', 'not ilike', 'Outstanding balance%')]),
]:
    pd_, t_ = withdate(dom, 'payment_date')
    dd_, _ = withdate(dom, 'due_date')
    print('  %-22s payment_date %3s/%-3s   due_date %3s/%-3s' % (label, pd_, t_, dd_, t_))

line('CONTRACT COUNT RECONCILIATION')
print('  contracts with summary lines    = %d' % len(scon))
print('  contracts with milestone lines  = %d' % len(set(
    I.search(ICO + [('name', 'not ilike', 'Collected to date%'),
                    ('name', 'not ilike', 'Outstanding balance%')]).mapped('contract_id').ids)))
print('  sold contracts                  = %d' % S.search_count(CO + [('state', 'in', ('signed', 'completed'))]))
print('  contracts with ZERO installments= %d' % S.search_count(CO + [('state', 'in', ('signed', 'completed'))]) - len(
    set(I.search(ICO).mapped('contract_id').ids)))

env.cr.rollback()
print(''); print('DONE (rolled back)')