# -*- coding: utf-8 -*-
"""Generate data for the unreconciled-items document."""
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
print('WB sold by proj:', sold.groupby('proj').size().to_dict(), 'total', len(sold))
sold['escrow_pct']=pd.to_numeric(sold['Escrow %'],errors='coerce')
sold['expected']=sold['escrow_pct']*pd.to_numeric(sold['Sold Price (AED)'],errors='coerce')
sold['allocated']=pd.to_numeric(sold['Escrow Allocated (AED)'],errors='coerce')
def status(r):
    if pd.isna(r.escrow_pct) or r.escrow_pct==0 and pd.isna(r.allocated) and pd.isna(r.allocated):
        pass
    if pd.isna(r.escrow_pct):
        return 'NO_ESCROW_PCT'
    if pd.isna(r.allocated):
        return 'NO_ALLOCATION'
    if abs(r.allocated-r.expected)>1:
        return 'UNDER' if r.allocated<r.expected else 'OVER'
    return 'OK'
sold['st']=sold.apply(status,axis=1)
print(sold.st.value_counts().to_dict())
bad=sold[sold.st!='OK'].copy()
bad['var']=bad.allocated-bad.expected
print(bad[['proj','key','Client Name','Sold Price (AED)','escrow_pct','expected','allocated','var','st']].to_string())
# cross-check against staged escrow_deferred.json
esc=json.load(open('deferred/escrow_deferred.json',encoding='utf-8'))
edf=pd.DataFrame(esc)
mg=sold.merge(edf,on=['proj','unit'] if 'unit' in edf else ['proj','key'],how='inner',suffixes=('','_e')) if 'unit' in edf else None
edf['key']=edf['unit'].map(key)
mg=sold.merge(edf,on=['proj','key'],how='inner',suffixes=('','_e'))
print('staged coverage: both',len(mg),'| wb only',len(sold)-len(mg),'| staged only',len(edf)-len(mg))
d1=(mg.escrow_pct-mg.escrow_pct_e).abs(); d2=(mg.allocated.fillna(0)-mg.escrow_allocated).abs()
print('staged vs WB(4): pct diff>1e-6:',(d1>1e-6).sum(),'| allocated diff>0.01:',(d2>0.01).sum())
print('wb-only (not in staged):',sold[sold.st.isin(['NO_ESCROW_PCT'])][['proj','key']].values.tolist())
# totals
print('escrow expected sum (pct>0):',round(sold[sold.escrow_pct>0].expected.sum(),2))
print('escrow allocated sum:',round(sold.allocated.sum(),2))
sold.to_pickle('sold5.pkl')
