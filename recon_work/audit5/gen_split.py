# -*- coding: utf-8 -*-
import pandas as pd, numpy as np, json, re
M={'PGV':'GOLF','PBR1':'BR1','PBR2':'BR2','PRY':'RES'}
wb=pd.read_excel('C:/Parkgroup Data/Consolidated_Sales_Workbook (4).xlsx',sheet_name='All Units',header=5).iloc[:,1:]
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
na=bad[bad.st=='NO_ALLOCATION']
print('NO_ALLOCATION pct>0:',int((na.escrow_pct>0).sum()),'expected sum:',round(na[na.escrow_pct>0].expected.sum(),2))
print('NO_ALLOCATION pct=0:',int((na.escrow_pct==0).sum()))
print('OVER:',bad[bad.st=='OVER'][['proj','key','var']].values.tolist())
print('UNDER:')
for _,r in bad[bad.st=='UNDER'].iterrows():
    print(f"  {r.proj}/{r.key} {str(r['Client Name'])[:35]} var={r.allocated-r.expected:,.2f}")
print('NA pct>0 units:')
for _,r in na[na.escrow_pct>0].iterrows():
    print(f"  {r.proj}/{r.key} {str(r['Client Name'])[:35]} expected={r.expected:,.0f}")
