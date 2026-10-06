qweb = env['ir.qweb'].sudo()

print('=== Forcing real bundle build: web.assets_backend ===')
try:
    bundle = qweb._get_asset_bundle('web.assets_backend', css=True, js=True)
except Exception as e:
    print('  ERROR on _get_asset_bundle: %s: %s' % (type(e).__name__, e))
    bundle = None

if bundle is None:
    try:
        bundle = qweb._get_asset_content('web.assets_backend')
    except Exception as e:
        print('  ERROR on _get_asset_content: %s: %s' % (type(e).__name__, e))
        env.cr.rollback()
        raise SystemExit(1)

def as_text(x):
    if isinstance(x, (list, tuple)):
        return '\n'.join(as_text(i) for i in x)
    if isinstance(x, dict):
        return '\n'.join(as_text(v) for v in x.values())
    if isinstance(x, bytes):
        return x.decode('utf-8', 'replace')
    return str(x)

js_t = as_text(bundle)
print('  backend bundle length = %d chars' % len(js_t))

print('')
print('=== Required dashboard probes in web.assets_backend ===')
probes = {
    '_buildCards'          : 'card builder (no hardcoded values)',
    'state.cards'          : 'cards bound to state',
    'RentalPropertyDashboard': 'OWL component',
    'property_dashboard'   : 'action tag registration',
    'sgc-kpi-row'          : 'v2 CSS grid class',
    'sgc-watchlist'        : 'watchlist CSS',
    'sgc-table'            : 'project table CSS',
    'sgc-map'              : 'map CSS',
    'Leaflet'              : 'Leaflet lib present',
    'echarts'              : 'ECharts lib present',
    'aging_undated'        : 'aging undated payload key',
}
ok = True
for probe, desc in probes.items():
    hit = probe in js_t
    ok = ok and hit
    print('  %-24s %-38s %s' % (probe, desc, 'FOUND' if hit else 'MISSING'))

print('')
print('=== QWeb template probes (the compiled dashboard template) ===')
for probe in ['RentalPropertyDashboard', 'sgc-kpi-row', 'sgc-watchlist',
              'sgc-table', 'sgc-map', 'sgc-chart']:
    hit = probe in js_t
    print('  %-24s %s' % (probe, 'FOUND' if hit else 'MISSING'))

env.cr.rollback()
print('')
print('BUNDLE_BUILD_%s' % ('OK' if ok else 'INCOMPLETE'))
print('DONE (rolled back)')