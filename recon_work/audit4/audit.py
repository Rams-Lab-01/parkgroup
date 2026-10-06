import pandas as pd, numpy as np, re, json
M={'PGV':'GOLF','PBR1':'BR1','PBR2':'BR2','PRY':'RES'}
wb=pd.read_excel('C:/Parkgroup Data/Consolidated_Sales_Workbook (4).xlsx',sheet_name='All Units',header=5).iloc[:,1:]
wb=wb[wb['Project Name'].isin(M)].copy()
def key(v):
    s=str(v).strip()
    s=re.sub(r'^Unit\s+','',s)
    if re.fullmatch(r'\d+\.0',s): s=s[:-2]
    return s
wb['proj']=wb['Project Name'].map(M); wb['key']=wb['Unit No'].map(key)
u=pd.read_csv('a_units.csv',dtype={'unit_number':str}); c=pd.read_csv('a_contracts.csv',dtype={'unit_number':str})
u['key']=u.unit_number.map(key); c['key']=c.unit_number.map(key)
print('wb units',len(wb),'dup keys',wb.duplicated(['proj','key']).sum(),'| db units',len(u),'contracts',len(c))
print(wb.groupby('proj').size().to_dict(), u.groupby('proj').size().to_dict())
m=wb.merge(u,on=['proj','key'],how='outer',indicator=True,suffixes=('','_db'))
print(m._merge.value_counts().to_dict())
print('ONLY WB:',m[m._merge=='left_only'][['proj','key','Status']].values.tolist())
print('ONLY DB:',m[m._merge=='right_only'][['proj','key','state']].values.tolist())
b=m[m._merge=='both'].copy()
b['wb_sold']=b.Status.str.lower().str.contains('sold')
print(b.Status.value_counts().to_dict())
print('state mismatch', pd.crosstab(b.wb_sold,b.state))
for col,dbc in [('Sold Price (AED)','sale_price'),('List Price (AED)','price'),('Size (Sq Ft)','area')]:
    d=(pd.to_numeric(b[col],errors='coerce')-pd.to_numeric(b[dbc],errors='coerce')).abs()
    print(col,'diff>1:',(d>1).sum(),'| wb null/db notnull', (b[col].isna()&b[dbc].notna()).sum())
b.to_pickle('b.pkl'); wb.to_pickle('wb.pkl'); c.to_pickle('c.pkl'); u.to_pickle('u.pkl')
