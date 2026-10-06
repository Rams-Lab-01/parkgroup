D = env['property.details']
pd = D.search([], limit=1)
payload = pd.get_development_kpis()

print('=== watchlist_counts (server, real) ===')
wc = payload.get('watchlist_counts')
print('  %s' % wc)

print('')
print('=== cross-check watchlist counts against DB ===')
A = env['escrow.allocation'].sudo()
dom = [('company_id', 'in', env.companies.ids)]
rec = A.search_count([('company_id', 'in', env.companies.ids),
                      ('has_source_data', '=', True),
                      ('variance_amount', '<=', 0.01),
                      ('variance_amount', '>=', -0.01)])
und = A.search_count([('company_id', 'in', env.companies.ids),
                      ('variance_amount', '>', 0.01)])
ovr = A.search_count([('company_id', 'in', env.companies.ids),
                      ('variance_amount', '<', -0.01)])
awt = A.search_count([('company_id', 'in', env.companies.ids),
                      ('has_source_data', '=', False)])
print('  DB reconciled      = %d  | payload %s' % (rec, wc.get('reconciled')))
print('  DB under-allocated = %d  | payload %s' % (und, wc.get('under_allocated')))
print('  DB over-allocated  = %d  | payload %s' % (ovr, wc.get('over_allocated')))
print('  DB awaiting source = %d  | payload %s' % (awt, wc.get('awaiting_source')))
match = (rec == wc.get('reconciled') and und == wc.get('under_allocated')
         and ovr == wc.get('over_allocated') and awt == wc.get('awaiting_source'))
print('  MATCH: %s' % ('YES' if match else '*** NO ***'))

print('')
print('=== project_map (now carries name/city/units) ===')
for code, m in payload['project_map'].items():
    print('  %-5s name=%-24s city=%-16s lat=%-9s lon=%-9s units=%-4s sold=%s' % (
        code, m['name'], m['city'], m['lat'], m['lon'], m['units'], m['count']))

print('')
print('=== project_map totals reconcile ===')
print('  sum(map.units) = %s (total_units=%s)' % (
    sum(m['units'] for m in payload['project_map'].values()), payload['total_units']))
print('  sum(map.count) = %s (sold_units=%s)' % (
    sum(m['count'] for m in payload['project_map'].values()), payload['sold_units']))
print('  sum(per_project.sold) = %s (sold_units=%s)' % (
    sum(p['sold'] for p in payload['per_project'].values()), payload['sold_units']))

print('')
print('=== headline KPIs unchanged ===')
for k in ['total_units', 'sold_units', 'available_units', 'sell_through_pct',
          'sales_value', 'collected', 'balance_due', 'collection_pct', 'dso_days',
          'recon_rate', 'funded_pct', 'escrow_shortfall']:
    print('  %-22s %s' % (k, payload[k]))

print('')
print('=== payload key count = %d ===' % len(payload))
print('  watchlist_counts in payload: %s' % ('watchlist_counts' in payload))

env.cr.rollback()
print('')
print('DONE (rolled back - read only)')