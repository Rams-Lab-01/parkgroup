import traceback

qweb = env['ir.qweb'].sudo()

print('=== Generating + committing asset bundle cache ===')
try:
    b = qweb._get_asset_bundle('web.assets_backend', css=True, js=True)
    js_urls = b.js()
    css_urls = b.css()
    print('  js url(s)  = %s' % (js_urls,))
    print('  css url(s) = %s' % (css_urls,))
except Exception:
    print('  build FAILED')
    traceback.print_exc()
    env.cr.rollback()
    raise SystemExit(1)

env.cr.commit()
print('  committed asset cache')

print('')
print('=== Reading committed bundle attachments and probing content ===')
results = {}
for name in ('web.assets_backend.min.js', 'web.assets_backend.min.css'):
    att = env['ir.attachment'].sudo().search([('name', '=', name)], order='id desc', limit=1)
    if not att:
        print('  %s : NOT FOUND' % name)
        results[name] = ''
        continue
    raw = att.db_datas or b''
    txt = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
    results[name] = txt
    print('  %-32s id=%s bytes=%s chars=%d' % (name, att.id, att.file_size, len(txt)))

js_t = results.get('web.assets_backend.min.js', '')
css_t = results.get('web.assets_backend.min.css', '')

print('')
print('=== JS probes (must ALL be FOUND) ===')
js_ok = True
for probe, desc in [
    ('_buildCards',          'data-driven card builder'),
    ('this.state.cards',     'cards bound to OWL state'),
    ('RentalPropertyDashboard', 'OWL component'),
    ('add("property_dashboard"', 'action tag registration'),
    ('Leaflet',              'Leaflet lib in bundle'),
    ('echarts',              'ECharts lib in bundle'),
    ('aging_undated',        'aging payload key used'),
    ('renderMap',            'map renderer'),
    ('get_development_kpis', 'server KPI call'),
]:
    hit = probe in js_t
    js_ok = js_ok and hit
    print('  %-28s %-32s %s' % (probe, desc, 'FOUND' if hit else '*** MISSING ***'))

print('')
print('=== Compiled QWeb dashboard template inside bundle ===')
tpl_ok = True
for probe in ['sgc-kpi-row', 'sgc-watchlist', 'sgc-table', 'sgc-map', 'sgc-chart']:
    hit = probe in js_t
    tpl_ok = tpl_ok and hit
    print('  %-18s %s' % (probe, 'FOUND' if hit else '*** MISSING ***'))

print('')
print('=== CSS probes (must ALL be FOUND) ===')
css_ok = True
for probe, desc in [
    ('.sgc-kpi-row',   '6-col KPI grid'),
    ('.sgc-watchlist', 'watchlist panel'),
    ('.sgc-table',     'project table'),
    ('.sgc-map',       'map block'),
    ('.sgc-chart',     'chart panel'),
]:
    hit = probe in css_t
    css_ok = css_ok and hit
    print('  %-18s %-32s %s' % (probe, desc, 'FOUND' if hit else '*** MISSING ***'))

print('')
print('=== Placeholder / hardcode audit ===')
bad = []
for w in ['TODO', 'FIXME', 'Lorem ipsum', 'DUMMY', 'SAMPLE_DATA']:
    if w in js_t:
        i = js_t.find(w)
        bad.append('%s -> ...%s...' % (w, js_t[max(0, i-50):i+50].replace('\n', ' ')))
print('  ' + ('\n  '.join(bad) if bad else 'clean - no TODO/FIXME/Lorem/DUMMY markers'))

print('')
print('FINAL js=%s template=%s css=%s placeholders=%s' % (
    'OK' if js_ok else 'FAIL',
    'OK' if tpl_ok else 'FAIL',
    'OK' if css_ok else 'FAIL',
    'FOUND' if bad else 'CLEAN'))
print('DONE (committed)')