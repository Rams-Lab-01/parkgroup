import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_columns',40); pd.set_option('display.max_colwidth',40)
b=pd.read_pickle('b.pkl'); c=pd.read_pickle('c.pkl')
print('--- sold in DB but available in WB / price diffs')
x=b[(b.state=='sold')&(~b.wb_sold)][['proj','key','Status','state','Client Name','sale_price','Sold Price (AED)']]; print(x)
d=b[(pd.to_numeric(b['Sold Price (AED)'],errors='coerce')-pd.to_numeric(b.sale_price,errors='coerce')).abs()>1][['proj','key','Status','sale_price','Sold Price (AED)','List Price (AED)']]; print(d)
print('--- units with state sold but no contract:'); 
bc=b.merge(c,on=['proj','key'],how='left',suffixes=('','_c'),indicator='ci')
print(bc[(bc.wb_sold)&(bc.ci=='left_only')][['proj','key']].values.tolist())
print(bc[(~bc.wb_sold)&(bc.ci=='both')][['proj','key','cid']].values.tolist())
s=bc[bc.wb_sold&(bc.ci=='both')].copy()
num=lambda col: pd.to_numeric(s[col],errors='coerce')
s['d_price']=num('Sold Price (AED)')-s.sale_price
s['d_inst']=s.inst_sum-s.sale_price
s['d_paid']=num('Amount Collected (AED)')-s.total_paid
s['d_instpaid']=num('Amount Collected (AED)')-s.inst_paid
print('contracts',len(s))
for k in ['d_price','d_inst','d_paid','d_instpaid']:
    print(k,'nonzero(>1):',(s[k].abs()>1).sum(),'nan',s[k].isna().sum())
print(s[s.d_inst.abs()>1][['proj','key','sale_price','inst_sum','n_inst','d_inst']].head(30))
print(s[s.d_paid.abs()>1][['proj','key','Amount Collected (AED)','total_paid','inst_paid','d_paid']].head(30))
print('buyer blank/wb client blank', s['Client Name'].isna().sum(), '| name mismatch (norm):')
n=lambda v:''.join(ch for ch in str(v).lower() if ch.isalnum())
mm=s[s.apply(lambda r:n(r['Client Name'])!=n(r.buyer),axis=1)][['proj','key','Client Name','buyer']]
print(len(mm)); print(mm.head(25))
print('contact diff',(s.apply(lambda r:n(r['Contact No'])!=n(r.phone) ,axis=1)).sum(),' email diff',(s.apply(lambda r:str(r['Email']).strip().lower()!=str(r.email).strip().lower(),axis=1)).sum())
print('n_inst dist',s.n_inst.value_counts().to_dict(), 'state',s.state.value_counts().to_dict(),'sched null',s.payment_schedule_id.isna().sum())
s.to_pickle('s.pkl')
