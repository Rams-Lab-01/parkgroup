import csv
from datetime import date
import openpyxl

WB = r'C:\Parkgroup Data\Consolidated_Sales_Workbook (4).xlsx'
DB = r'C:\Parkgroup Data\recon_work\dashboard\dash_contracts.csv'
REF = date(2026, 10, 5)  # workbook generation date

MAP = {'PBR1': 'BR1', 'PBR2': 'BR2', 'PRY': 'RES', 'PGV': 'GOLF'}

def norm_unit(u):
    if u is None:
        return ''
    s = str(u).strip()
    if s.lower().startswith('unit '):
        s = s[5:]
    if s.endswith('.0'):
        s = s[:-2]
    return s

def d(v):
    if v is None or v == '':
        return None
    if isinstance(v, date):
        return v
    s = str(v).strip()[:10]
    try:
        y, m, dd = s.split('-')
        return date(int(y), int(m), int(dd))
    except Exception:
        return None

# --- workload: DB ---
db = {}
with open(DB, encoding='utf-8') as f:
    for row in csv.DictReader(f):
        key = (row['proj'], norm_unit(row['unit']))
        last_pay = d(row['last_pay'])
        cdate = d(row['contract_date'])
        activity = last_pay or cdate
        aging = (REF - activity).days if activity else None
        db[key] = {
            'sale_price': float(row['sale_price'] or 0),
            'total_paid': float(row['total_paid'] or 0),
            'last_pay': last_pay,
            'cdate': cdate,
            'activity': activity,
            'aging': aging,
        }

print('DB contracts:', len(db))

# --- workbook ---
wb = openpyxl.load_workbook(WB, data_only=True, read_only=True)
ws = wb['Unit Payment Collection']
rows = list(ws.iter_rows(values_only=True))
hdr = None
for i, r in enumerate(rows):
    if r and r[1] is not None and str(r[1]).strip() == 'Project Name':
        hdr = i
        break
print('header row idx:', hdr)

wb_sold = 0
mismatch_activity = []
aging_db = {'0-30': 0, '31-60': 0, '61-90': 0, '91-180': 0, '180+': 0, 'NO_AGING': 0}
aging_wb = dict(aging_db)
missing_in_db = []
count_bal_wb = 0

def bucket(a):
    if a is None:
        return 'NO_AGING'
    if a <= 30: return '0-30'
    if a <= 60: return '31-60'
    if a <= 90: return '61-90'
    if a <= 180: return '91-180'
    return '180+'

for r in rows[hdr+1:]:
    if not r or not r[1]:
        continue
    proj = MAP.get(str(r[1]).strip(), str(r[1]).strip())
    unit = norm_unit(r[2])
    status = str(r[4] or '').strip()
    if status != 'Sold':
        continue
    wb_sold += 1
    key = (proj, unit)
    wb_activity = d(r[18])
    wb_aging = r[19]
    bal = r[16]
    if bal not in (None, ''):
        try:
            if float(bal) > 0.01:
                count_bal_wb += 1
        except Exception:
            pass
    if key not in db:
        missing_in_db.append(key)
        continue
    e = db[key]
    if wb_activity != e['activity']:
        mismatch_activity.append((key, wb_activity, e['activity'], e['last_pay'], e['cdate']))
    aging_db[bucket(e['aging'])] += 1
    try:
        wb_a = int(wb_aging) if wb_aging not in (None, '') else None
    except Exception:
        wb_a = None
    aging_wb[bucket(wb_a)] += 1

print('wb sold rows:', wb_sold, '| wb rows w/ balance>0:', count_bal_wb)
print('missing in DB:', len(missing_in_db), missing_in_db[:10])
print('activity mismatches:', len(mismatch_activity))
for m in mismatch_activity[:15]:
    print('  MISMATCH', m)
print('aging DB calc :', aging_db)
print('aging WB      :', aging_wb)
