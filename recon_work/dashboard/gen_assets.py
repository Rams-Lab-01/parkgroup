assets = env['ir.asset'].sudo().search([
    ('path', 'like', 'rental_property_dashboard'),
])
print('--- ir.asset records for dashboard files ---')
for a in assets:
    print('  bundle=%-32r path=%r' % (a.bundle, a.path))
print('  count=%d' % len(assets))

print('')
print('--- generation methods on ir.asset ---')
print('  ' + ', '.join(m for m in dir(env['ir.asset'])
                        if 'generat' in m.lower() or 'content' in m.lower()))

print('')
print('--- generating web.assets_web bundle ---')
content = None
try:
    res = env['ir.asset'].sudo()._generate_asset_content('web.assets_web')
    content = res.get('content') if isinstance(res, dict) else res
except TypeError:
    try:
        res = env['ir.asset'].sudo()._generate_asset_content('web.assets_web', 'web.assets_web')
        content = res.get('content') if isinstance(res, dict) else res
    except Exception as e2:
        print('  failed: %s: %s' % (type(e2).__name__, e2))
except Exception as e:
    print('  failed: %s: %s' % (type(e).__name__, e))

if content:
    if isinstance(content, bytes):
        content = content.decode('utf-8', 'replace')
    print('  generated length=%d' % len(content))
    for probe in ['_buildCards', 'sgc-kpi-row', 'RentalPropertyDashboard',
                  'state.cards.slice', 'sgc-watchlist', 'sgc-table',
                  'this[card.action]', 'formatPct', 'sgc-leaflet-pin']:
        print('  %-26s present=%s' % (probe, probe in content))
else:
    print('  NO CONTENT GENERATED')

env.cr.rollback()
print('')
print('DONE (rolled back)')