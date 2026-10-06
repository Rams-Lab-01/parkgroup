# -*- coding: utf-8 -*-
doc=open(r'C:\Parkgroup Data\Parkgroup_Unreconciled_Items_2026-10-05.md',encoding='utf-8').read()
tab=open(r'C:\Parkgroup Data\recon_work\audit5\escrow_table.md',encoding='utf-8').read().rstrip()
marker='```\nescrow-table\n```'
if marker in doc:
    doc=doc.replace(marker, tab+'\n')
else:
    doc=doc.replace('escrow-table', tab, 1)
open(r'C:\Parkgroup Data\Parkgroup_Unreconciled_Items_2026-10-05.md','w',encoding='utf-8').write(doc)
rows=[l for l in doc.splitlines() if l.startswith('| BR') or l.startswith('| RES') or l.startswith('| GOLF')]
print('table data rows:', len(rows))
print('doc chars:', len(doc))
print('placeholder left:', 'escrow-table' in doc)
