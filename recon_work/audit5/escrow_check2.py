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
esc=json.load(open('deferred/escrow_deferred.json',encoding='utf-8'))
edf=pd.DataFrame(esc)
edf['key']=edf['unit'].map(key)
edf=edf.rename(columns={'project':'proj'})
mg=sold.merge(edf,on=['proj','key'],how='inner',suffixes=('','_e'))
print('staged rows:',len(edf),'| matched:',len(mg),'| sold not staged:',sorted(set(map(tuple, sold[sold.st!="stg"][["proj","key"]].values if False else sold[~sold.index.isin(mg.index)][["proj","key"]].values))))
d1=(mg.escrow_pct-mg.escrow_pct_e).abs(); d2=(mg.allocated.fillna(0)-mg.escrow_allocated.fillna(0)).abs()
ds=(mg['Sold Price (AED)']-mg.sold).abs() if 'Sold Price (AED)' in mg else None
print('staged vs WB(4): pct diff>1e-6:',(d1>1e-6).sum(),'| allocated diff>0.01:',(d2>0.01).sum(),'| sold diff>0.01:',(ds>0.01).sum() if ds is not None else 'n/a')
print('expected escrow sum (pct>0):',round(sold[sold.escrow_pct>0].expected.sum(),2))
print('allocated escrow sum:',round(sold.allocated.sum(),2))
print('expected among UNDER/OVER/NO_ALLOC with pct>0:',round(sold[sold.st.isin(['UNDER','OVER','NO_ALLOCATION'])&(sold.escrow_pct>0)].expected.sum(),2))
