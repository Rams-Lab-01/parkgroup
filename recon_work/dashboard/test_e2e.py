from datetime import timedelta, date

D = env['property.details'].sudo()
S = env['sale.contract'].sudo()
A = env['escrow.allocation'].sudo()
CO = [('company_id', 'in', env.companies.ids)]

def line(t):
    print(''); print('=' * 74); print(t); print('=' * 74)

pd = D.search([], limit=1)
pl = pd.get_development_kpis()
d90 = (date.today() - timedelta(days=90)).isoformat()

def show(card, displayed, action, m, domain):
    n = m.sudo().search_count(CO + domain)
    print('  %-22s shown=%-20s -> %-22s %d records' % (card, displayed, action, n))
    return n

line('E2E DRILL-DOWN: every card now opens the population it displays')

print('')
print('--- inventory (property.details) ---')
show('Total Units', pl['total_units'], 'viewAllProperties', D, [])
show('Sold Units', pl['sold_units'], 'viewSoldProperties', D, [('state', 'in', ('sold', 'completed'))])
show('Available Units', pl['available_units'], 'viewAvailableProperties', D, [('state', '=', 'available')])
show('Sell-Through', '%.2f%%' % pl['sell_through_pct'], '(derived)', D, [])
show('Avg PSF', pl['avg_psf_sold'], 'viewSoldProperties', D, [('state', 'in', ('sold', 'completed'))])

print('')
print('--- receivables (sale.contract) ---')
n_out = show('Balance Due', pl['balance_due'], 'viewOutstanding', S, [('balance_due', '>', 0.01)])
s_out = sum(r.balance_due or 0 for r in S.search(CO + [('balance_due', '>', 0.01)]))
print('       outstanding drill SUM = %s  vs card %s  (diff %s)' % (
    round(s_out, 2), pl['balance_due'], round(s_out - pl['balance_due'], 2)))
show('DSO', '%sd' % round(pl['dso_days']), 'viewOutstanding', S, [('balance_due', '>', 0.01)])
n_aged = show('Aged > 90 Days', pl['aged_overdue_units'], 'viewAgedOverdue', S,
              [('balance_due', '>', 0.01), ('last_activity_date', '<=', d90)])
s_aged = sum(r.balance_due or 0 for r in S.search(CO + [('balance_due', '>', 0.01), ('last_activity_date', '<=', d90)]))
print('       aged drill SUM = %s  vs card amount %s' % (round(s_aged, 2), pl['aged_overdue_amount']))
print('       subset check: aged(%d) <= outstanding(%d) : %s' % (
    n_aged, n_out, 'PASS' if n_aged <= n_out else 'FAIL'))

print('')
print('--- escrow (escrow.allocation) ---')
n_all = show('Expected Escrow', pl['required_escrow'], 'viewAllAllocations', A, [])
s_all = sum(r.required_amount or 0 for r in A.search(CO))
print('       all-allocations SUM = %s vs card %s' % (round(s_all, 2), pl['required_escrow']))
n_ws = show('Allocated Escrow', pl['allocated_escrow'], 'viewWithSource', A, [('has_source_data', '=', True)])
s_ws = sum(r.allocated_amount or 0 for r in A.search(CO + [('has_source_data', '=', True)]))
print('       with-source SUM = %s vs card %s  (diff %s = awaiting-source funds)' % (
    round(s_ws, 2), pl['allocated_escrow'], round(pl['allocated_escrow'] - s_ws, 2)))
n_und = show('Escrow Shortfall', pl['escrow_shortfall'], 'viewUnderAllocated', A, [('variance_amount', '<', -0.01)])
s_und = sum((r.required_amount or 0) - (r.allocated_amount or 0) for r in A.search(CO + [('variance_amount', '<', -0.01)]))
print('       under-allocated shortfall SUM = %s (card total shortfall %s, remainder = awaiting-source)' % (
    round(s_und, 2), pl['escrow_shortfall']))
show('Funded Rate', '%.1f%%' % pl['funded_pct'], 'viewWithSource', A, [('has_source_data', '=', True)])
n_rec = show('Reconciliation Rate', '%.1f%%' % pl['recon_rate'], 'viewReconciled', A,
             [('has_source_data', '=', True), ('variance_amount', '<=', 0.01), ('variance_amount', '>=', -0.01)])
n_awt = show('Missing Source', pl['missing_source_count'], 'viewAwaitingSource', A, [('has_source_data', '=', False)])

line('CROSS-CHECKS')
print('  reconciled %d + awaiting %d = %d (all=%d): %s' % (
    n_rec, n_awt, n_rec + n_awt, n_all, 'PASS' if n_rec + n_awt == n_all else 'FAIL'))
print('  under %d + over + reconciled = ?' % n_und)
n_ovr = A.search_count(CO + [('variance_amount', '>', 0.01)])
print('  under %d + over %d + reconciled %d = %d ; all %d ; remainder(with source, var==0) = %d' % (
    n_und, n_ovr, n_rec, n_und + n_ovr + n_rec, n_all, n_all - n_und - n_ovr - n_rec))
print('  watchlist_counts payload = %s' % pl['watchlist_counts'])
print('  payload under/over must be %d/%d : %s' % (
    n_und, n_ovr, 'PASS' if (pl['watchlist_counts']['under_allocated'] == n_und
                             and pl['watchlist_counts']['over_allocated'] == n_ovr) else 'FAIL'))

line('ESCROW DOLLAR RECONCILIATION (both directions)')
req_all = sum(r.required_amount or 0 for r in A.search(CO))
alc_all = sum(r.allocated_amount or 0 for r in A.search(CO))
print('  sum(required)  = %s' % round(req_all, 2))
print('  sum(allocated) = %s' % round(alc_all, 2))
print('  difference     = %s  (card shortfall = %s)' % (
    round(req_all - alc_all, 2), pl['escrow_shortfall']))
print('  card required  = %s : %s' % (pl['required_escrow'], 'PASS' if abs(req_all - pl['required_escrow']) < 0.02 else 'FAIL'))
print('  card allocated = %s : %s' % (pl['allocated_escrow'], 'PASS' if abs(alc_all - pl['allocated_escrow']) < 0.02 else 'FAIL'))
print('  shortfall = required - allocated : %s' % (
    'PASS' if abs((req_all - alc_all) - pl['escrow_shortfall']) < 0.02 else 'FAIL'))
print('  funded_pct = allocated/required = %.2f%% : %s' % (
    alc_all / req_all * 100 if req_all else 0,
    'PASS' if abs((alc_all / req_all * 100) - pl['funded_pct']) < 0.05 else 'FAIL'))

env.cr.rollback()
print(''); print('DONE (rolled back)')