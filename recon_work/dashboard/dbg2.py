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
print('--- wb sold rows with BLANK aging ---')
for r in rows[hdr+1:]:
    if not r or not r[1]:
        continue
    status = str(r[4] or '').strip()
    if status != 'Sold':
        continue
    aging = r[19]
    if aging in (None, ''):
        print(r[1], repr(r[2]), '| collected=', r[14], '| coll%=', r[15], '| bal=', r[16], '| coll_status=', r[17], '| last_activity=', r[18], '| 10%=', r[9], '| 20%=', r[12])
print()
print('--- wb sold rows aging 0..30 ---')
for r in rows[hdr+1:]:
    if not r or not r[1]:
        continue
    status = str(r[4] or '').strip()
    if status != 'Sold':
        continue
    try:
        a = int(r[19])
    except Exception:
        continue
    if 0 <= a <= 30:
        print(r[1], repr(r[2]), '| aging=', a, '| bal=', r[16], '| last_activity=', r[18])
