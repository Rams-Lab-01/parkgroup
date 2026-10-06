# -*- coding: utf-8 -*-
"""Full re-audit: Consolidated_Sales_Workbook (4).xlsx vs current DB snapshot (s_*.csv) + staged deferred data."""
import pandas as pd, numpy as np, re, json, io, sys
pd.set_option('display.width',260); pd.set_option('display.max_columns',40); pd.set_option('display.max_colwidth',45)

M={'PGV':'GOLF','PBR1':'BR1','PBR2':'BR2','PRY':'RES'}
wb=pd.read_excel('C:/Parkgroup Data/Consolidated_Sales_Workbook (4).xlsx',sheet_name='All Units',header=5).iloc[:,1:]
wb=wb[wb['Project Name'].isin(M)].copy()
def key(v):
    s=str(v).strip(); s=re.sub(r'^Unit\s+','',s)
    if re.fullmatch(r'\d+\.0',s): s=s[:-2]
    return s
wb['proj']=wb['Project Name'].map(M); wb['key']=wb['Unit No'].map(key)
u=pd.read_csv('s_units.csv',dtype={'unit_number':str}); c=pd.read_csv('s_contracts.csv',dtype={'unit_number':str}); i=pd.read_csv('s_inst.csv',dtype={'unit_number':str})
u['key']=u.unit_number.map(key); c['key']=c.unit_number.map(key); i['key']=i.unit_number.str.replace(r'\.0$','',regex=True)
wb['Status']=wb['Status'].astype(str).str.strip()
wb['wb_sold']=wb.Status.str.lower().str.contains('sold')

out=io.StringIO()
def P(*a):
    s=' '.join(str(x) for x in a); print(s); out.write(s+'\n')

P('== UNITS ==')
P('wb units',len(wb),'dup',wb.duplicated(['proj','key']).sum(),'| db units',len(u),'contracts',len(c),'installments',len(i))
P('wb by proj',wb.groupby('proj').size().to_dict()); P('db by proj',u.groupby('proj').size().to_dict())
mu=wb.merge(u,on=['proj','key'],how='outer',indicator=True,suffixes=('','_db'))
P('merge',mu._merge.value_counts().to_dict())
P('ONLY WB:',mu[mu._merge=='left_only'][['proj','key','Status']].values.tolist())
P('ONLY DB:',mu[mu._merge=='right_only'][['proj','key','state']].values.tolist())
b=mu[mu._merge=='both'].copy()
P('wb status',wb.wb_sold.value_counts().to_dict())
P('state crosstab (rows=wb_sold, cols=db state):'); P(pd.crosstab(b.wb_sold,b.state))
for col,dbc in [('Sold Price (AED)','sale_price'),('List Price (AED)','price'),('Size (Sq Ft)','area')]:
    d=(pd.to_numeric(b[col],errors='coerce')-pd.to_numeric(b[dbc],errors='coerce')).abs()
    P(col,'diff>1:',(d>1).sum())
b.to_pickle('b5.pkl')

P('')
P('== CONTRACTS ==')
bc=b.merge(c,on=['proj','key'],how='left',suffixes=('','_c'),indicator='ci')
P('sold in WB but no contract:',bc[(bc.wb_sold)&(bc.ci=='left_only')][['proj','key','Status']].values.tolist())
P('not-sold in WB but has contract:',bc[(~bc.wb_sold)&(bc.ci=='both')][['proj','key','Status','cname']].values.tolist())
s=bc[bc.wb_sold&(bc.ci=='both')].copy()
P('matched sold contracts:',len(s))
s['d_price']=pd.to_numeric(s['Sold Price (AED)'],errors='coerce')-s.sale_price
s['d_inst']=s.inst_sum-s.sale_price
s['d_paid']=pd.to_numeric(s['Amount Collected (AED)'],errors='coerce')-s.total_paid
s['d_instpaid']=pd.to_numeric(s['Amount Collected (AED)'],errors='coerce')-s.inst_paid
for k in ['d_price','d_inst','d_paid','d_instpaid']:
    P(k,'nonzero>1:',(s[k].abs()>1).sum())
P('price diffs>1:'); P(s[s.d_price.abs()>1][['proj','key','Client Name','sale_price','Sold Price (AED)']].to_string())
P('inst_sum diffs>1:'); P(s[s.d_inst.abs()>1][['proj','key','sale_price','inst_sum','n_inst','d_inst']].to_string())
P('collected diffs>1:'); P(s[s.d_paid.abs()>1][['proj','key','Amount Collected (AED)','total_paid','inst_paid']].to_string())

n=lambda v:''.join(ch for ch in str(v).lower() if ch.isalnum())
P('buyer name mismatches:')
mm=s[s.apply(lambda r:n(r['Client Name'])!=n(r.buyer),axis=1)]
P(len(mm)); P(mm[['proj','key','Client Name','buyer']].to_string())
P('')
P('== CONTACTS ==')
def nd(v):  # normalize phone: keep digits
    return re.sub(r'\D','',str(v))
s['phone_norm']=s['Contact No'].map(nd); s['db_phone_norm']=s.phone.map(nd)
ct=s[s.phone_norm!=s.db_phone_norm]
P('contact mismatches (digit-normalized):',len(ct))
P(ct[['proj','key','Client Name','Contact No','phone']].to_string())
P('full phone values present in wb but db truncated (db in wb):')
tr=ct[ct.apply(lambda r: str(r.phone).strip() in str(r['Contact No']),axis=1)]
P(len(tr)); P(tr[['proj','key','Client Name','Contact No','phone']].to_string())
P('wb phone empty:',s['Contact No'].isna().sum(),'db phone empty:',s.phone.isna().sum())
P('email mismatches (case-insens):')
em=s[s.Email.astype(str).str.strip().str.lower()!=s.email.astype(str).str.strip().str.lower()]
P(len(em)); P(em[['proj','key','Client Name','Email','email']].to_string())

P('')
P('== INSTALLMENT MILESTONES ==')
s['wb10']=pd.to_numeric(s['10% Amount (AED)'],errors='coerce'); s['wb20']=pd.to_numeric(s['20% Amount (AED)'],errors='coerce')
g=i.groupby(['proj','key'])
ig=g.apply(lambda d:pd.Series({'i_first':d.amount.iloc[0],'i_second':d.amount.iloc[1] if len(d)>1 else np.nan,'i_states':'|'.join(d.state),'i_names':'|'.join(d.name)})).reset_index()
t=s.merge(ig,on=['proj','key'],how='left')
P('inst groups missing:',t.i_first.isna().sum())
P('10% mismatches>1:',((t.wb10-t.i_first).abs()>1).sum(),'| 20% mismatches>1:',((t.wb20-t.i_second).abs()>1).sum())
P('wb10 null:',t.wb10.isna().sum(),'wb20 null:',t.wb20.isna().sum())
P(t[(t.wb10-t.i_first).abs()>1][['proj','key','wb10','i_first','wb20','i_second','sale_price','n_inst']].head(20).to_string())
P('inst states combos:',t.i_states.value_counts().head(10).to_dict())
P('inst name combos:',t.i_names.value_counts().head(10).to_dict())

P('')
P('== CONTROL TOTALS ==')
P('db contracts total_paid:',round(c.total_paid.sum(),2),'| paid installments:',round(i[i.state=="paid"].amount.sum(),2),'| wb sold price sum:',round(pd.to_numeric(s['Sold Price (AED)'],errors='coerce').sum(),2))
P('wb collected sum:',round(pd.to_numeric(s['Amount Collected (AED)'],errors='coerce').sum(),2))
s.to_pickle('s5.pkl'); out.write(out.getvalue())
open('audit5_report.txt','w',encoding='utf-8').write(out.getvalue())
P('report written.')
