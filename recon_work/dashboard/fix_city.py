P = env['property.project']
res = P.search([('name', '=', 'PARK Residency')], limit=1)
if not res:
    print('PARK Residency NOT FOUND')
else:
    print('before: id=%s name=%s city=%r lat=%s lon=%s' % (
        res.id, res.name, res.city, res.geo_latitude, res.geo_longitude))

    if res.city != 'Ras Al Khaimah':
        res.write({'city': 'Ras Al Khaimah'})
        print('  -> wrote city = Ras Al Khaimah')
    else:
        print('  -> already correct, no write')

    env.cr.commit()

    res.invalidate_recordset()
    print('after : id=%s name=%s city=%r' % (res.id, res.name, res.city))

print('')
print('=== all Park Group projects after correction ===')
for p in P.search([('name', 'like', 'PARK%')], order='name'):
    print('  %-24s city=%-16s lat=%-9s lon=%s' % (
        p.name, p.city, p.geo_latitude, p.geo_longitude))

print('')
print('=== KPI payload still healthy after write ===')
D = env['property.details']
pd = D.search([], limit=1)
payload = pd.get_development_kpis()
print('  total_units        = %s' % payload['total_units'])
print('  sold_units         = %s' % payload['sold_units'])
print('  available_units    = %s' % payload['available_units'])
print('  sell_through_pct   = %s' % payload['sell_through_pct'])
print('  sales_value        = %s' % payload['sales_value'])
print('  collected          = %s' % payload['collected'])
print('  balance_due        = %s' % payload['balance_due'])
print('  recon_rate         = %s' % payload['recon_rate'])
print('  projects in payload= %s' % len(payload['projects']))
for p in payload['projects']:
    print('     %-24s sold=%-4s units=%-4s city?=%s' % (
        p['name'], p['sold'], p['units'], p.get('city', '-')))

print('')
print('DONE (committed)')