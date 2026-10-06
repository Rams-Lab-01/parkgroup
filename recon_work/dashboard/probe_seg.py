import re

BUNDLE = '/var/lib/odoo/filestore/sgc_mt_parkgroup/ec/ec92a3f5af2a1c7d6fd1da18caeaeee1d53eba3e'
js = open(BUNDLE, encoding='utf-8', errors='replace').read()
print('bundle length = %d chars' % len(js))

# locate every module boundary marker
marks = [m.start() for m in re.finditer(r'@odoo-module', js)]
print('module markers found = %d' % len(marks))

# our component signature
i = js.find('class RentalPropertyDashboard')
print('class RentalPropertyDashboard at offset %d' % i)

# owning module = last marker before i
owner = max([m for m in marks if m < i], default=0)
nxt = [m for m in marks if m > i]
end = nxt[0] if nxt else len(js)
seg = js[owner:end]
print('owning module segment = %d chars (offset %d..%d)' % (len(seg), owner, end))

# identify which module it is
hdr = js[owner:owner + 400].replace('\n', ' ')
m = re.search(r'@odoo-module\s+([A-Za-z0-9_.]+)\s+alias="([^"]+)"', hdr)
if not m:
    m = re.search(r'@odoo-module\s+([A-Za-z0-9_.]+)', hdr)
print('owning module = %s' % (m.group(0)[:120] if m else 'unknown'))

print('')
print('=== audit INSIDE our module segment only ===')
clean = True
for w in ['TODO', 'FIXME', 'DUMMY', 'SAMPLE_DATA', 'Lorem ipsum']:
    hits = [mm.start() for mm in re.finditer(w, seg, re.I)]
    print('  %-12s count=%d' % (w, len(hits)))
    if hits:
        clean = False
        for h in hits[:3]:
            print('       ...%s...' % seg[max(0, h-70):h+70].replace('\n', ' '))

print('')
print('=== required content inside our module segment ===')
for probe in ['_buildCards', 'this.state.cards', 'add("property_dashboard"',
              'get_development_kpis', 'aging_undated', 'renderMap',
              'sgc-kpi-row', 'sgc-watchlist', 'sgc-table', 'sgc-map', 'sgc-chart']:
    hit = probe in seg
    print('  %-28s %s' % (probe, 'FOUND' if hit else '*** MISSING ***'))
    clean = clean and hit

print('')
print('OUR_MODULE_SEGMENT_%s' % ('CLEAN' if clean else 'HAS_ISSUES'))