#!/bin/sh
FS=/var/lib/odoo/filestore/sgc_mt_parkgroup
JS="$FS/ec/ec92a3f5af2a1c7d6fd1da18caeaeee1d53eba3e"

echo "=== context around each TODO in the production bundle ==="
grep -oE '.{90}TODO.{90}' "$JS" | nl

echo ""
echo "=== are any TODO markers inside OUR dashboard component? ==="
python3 - <<'PY'
import re
js = open('/var/lib/odoo/filestore/sgc_mt_parkgroup/ec/ec92a3f5af2a1c7d6fd1da18caeaeee1d53eba3e',
          encoding='utf-8', errors='replace').read()
i = js.find('class RentalPropertyDashboard')
j = js.find('/** @odoo-module', i + 10)
seg = js[i:j if j > i else i + 120000]
print('dashboard segment length = %d chars' % len(seg))
for w in ['TODO', 'FIXME', 'placeholder', 'DUMMY', 'hardcod']:
    n = len(re.findall(w, seg, re.I))
    print('  %-12s occurrences in dashboard segment = %d' % (w, n))
PY