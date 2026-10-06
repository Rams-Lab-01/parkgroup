# -*- coding: utf-8 -*-
import json
from collections import Counter
fl=json.load(open(r'C:\Parkgroup Data\recon_work\audit5\deferred\flags.json',encoding='utf-8'))
print('total flags:', len(fl))
for k,v in Counter(f['kind'] for f in fl).items(): print(' ',k,v)
print('BREAKDOWN units:', [f"{f['project']}/{f['unit']}" for f in fl if f['kind']=='BREAKDOWN_EXCEEDS_COLLECTED'])
print('OVERPAYMENT units:', [f"{f['project']}/{f['unit']}" for f in fl if f['kind']=='OVERPAYMENT'])
print('ODOO_SOLD_REPORT_NOT:', [f"{f['project']}/{f['unit']}" for f in fl if f['kind']=='ODOO_SOLD_REPORT_NOT'])
