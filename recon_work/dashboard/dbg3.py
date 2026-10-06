import openpyxl
from datetime import date
WB = r'C:\Parkgroup Data\Consolidated_Sales_Workbook (4).xlsx'
wb = openpyxl.load_workbook(WB, data_only=True, read_only=True)
ws = wb['Unit Payment Collection']
rows = list(ws.iter_rows(values_only=True))
hdr = None
for i, r in enumerate(rows):
    if r and r[1] is not None and str(r[1]).strip() == 'Project Name':
        hdr = i
        break
sold = [r for r in rows[hdr+1:] if r and r[1] and str(r[4] or '').strip() == 'Sold']
print('sold rows:', len(sold))
bad = []
for r in sold:
    try:
        int(r[19])
    except Exception:
        bad.append(r)
print('non-int aging rows:', len(bad))
for r in bad:
    print(' ', r[1], repr(r[2]), '| aging=', repr(r[19]), '| coll%=', r[15], '| bal=', r[16], '| status=', r[17], '| last_activity=', r[18])
