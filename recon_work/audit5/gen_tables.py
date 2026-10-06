# -*- coding: utf-8 -*-
import pandas as pd, numpy as np, json, re
M={'PGV':'GOLF','PBR1':'BR1','PBR2':'BR2','PRY':'RES'}
wb=pd.read_excel('C:/Parkgroup Data/Consolidated_Sales_Workbox (4).xlsx'.replace('Workbox','Workbook'),sheet_name='All Units',header=5).iloc[:,1:]
wb=wb[wb['Project Name'].isin(M)].copy()
def key(v):
    s=str(v).strip(); s=re.sub(r'^Unit\s+','',s)
    if re.fullmatch(r'\d+\.0',s): s=s[:-2]
    return s
wb['proj']=wb['Project Name'].map(M); wb['key']=wb['Unit No'].map(key)
sold=wb[wb.Status.astype(str).str.lower().str.contains('sold')].copy()
sold['escrow_pct']=pd.to_numeric(sold['Escrow %'],errors='coerce')
sold['expected']=sold['escrow_pct']*pd.to_numeric(sold['Sold Price (AED)'],errors='coerce')
sold['allocated']=pd.to_numeric(sold['Escrow Allocated (AED)'],errors='coerce')
def status(r):
    if pd.isna(r.escrow_pct): return 'NO_ESCROW_PCT'
    if pd.isna(r.allocated): return 'NO_ALLOCATION'
    if abs(r.allocated-r.expected)>1:
        return 'UNDER' if r.allocated<r.expected else 'OVER'
    return 'OK'
sold['st']=sold.apply(status,axis=1)
bad=sold[sold.st!='OK'].copy()
bad['var']=bad.allocated.fillna(0)-bad.expected
def f2(x):
    return '' if pd.isna(x) else ('{:,.0f}'.format(x) if abs(x)>=100 else '{:,.2f}'.format(x))
def fpct(x):
    return '' if pd.isna(x) else ('{:.1%}'.format(x) if x<1 else '{:,.0f}'.format(x))
lines=[]
lines.append('| Project | Unit | Client | Sold Price (AED) | Escrow % | Expected (AED) | Allocated (AED) | Variance (AED) | Status |')
lines.append('|---|---|---|---:|---:|---:|---:|---:|---|')
order={'OVER':0,'UNDER':1,'NO_ALLOCATION':2,'NO_ESCROW_PCT':3}
bad=bad.sort_values(['st','proj','key'],key=lambda c: c.map(order) if c.name=='st' else c)
for _,r in bad.iterrows():
    status_lbl={'OVER':'Over-allocated','UNDER':'Under-allocated','NO_ALLOCATION':'No allocation data in source','NO_ESCROW_PCT':'No escrow % in source'}[r.st]
    lines.append(f"| {r.proj} | {r.key} | {str(r['Client Name'])[:45]} | {f2(r['Sold Price (AED)'])} | {fpct(r.escrow_pct)} | {f2(r.expected)} | {f2(r.allocated)} | {f2(r['var']) if pd.notna(r['var']) else ''} | {status_lbl} |")
open('escrow_table.md','w',encoding='utf-8').write('\n'.join(lines)+'\n')
# summary per status
agg={}
for st in ['OVER','UNDER','NO_ALLOCATION','NO_ESCROW_PCT']:
    sub=bad[bad.st==st]
    agg[st]=(len(sub), round(sub['var'].sum() if st!='NO_ESCROW_PCT' else 0,2))
print('summary:', agg)
print('expected total pct>0:', round(sold[sold.escrow_pct>0].expected.sum(),2))
print('allocated total:', round(sold.allocated.sum(),2))
print('expected outstanding (UNDER+OVER+NO_ALLOC, pct>0):', round(bad[bad.st.isin(['UNDER','OVER','NO_ALLOCATION'])].expected.sum(),2))
print('allocated among those:', round(bad[bad.st.isin(['UNDER','OVER','NO_ALLOCATION'])].allocated.sum(),2))
