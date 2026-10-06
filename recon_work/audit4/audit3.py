import pandas as pd, numpy as np
pd.set_option('display.width',260); pd.set_option('display.max_columns',40); pd.set_option('display.max_colwidth',45)
s=pd.read_pickle('s.pkl')
n=lambda v:''.join(ch for ch in str(v).lower() if ch.isalnum())
mm=s[s.apply(lambda r:n(r['Client Name'])!=n(r.buyer),axis=1)]
print(mm[['proj','key','Client Name','buyer','Contact No','phone','Email','email']])
inst=pd.read_csv('a_inst.csv',dtype={'unit_number':str}); inst['key']=inst.unit_number.str.replace(r'\.0$','',regex=True)
print(inst.state.value_counts().to_dict(), inst.name.value_counts().head(12).to_dict())
# milestone comparison
s['wb10']=pd.to_numeric(s['10% Amount (AED)'],errors='coerce'); s['wb20']=pd.to_numeric(s['20% Amount (AED)'],errors='coerce')
g=inst.groupby(['proj','key'])
i1=g.apply(lambda d:pd.Series({'i_first':d.amount.iloc[0],'i_second':d.amount.iloc[1] if len(d)>1 else np.nan,'names':'|'.join(d.name)})).reset_index()
t=s.merge(i1,on=['proj','key'])
print('names combos',t.names.value_counts().head(8).to_dict())
print('10% amount mismatch',((t.wb10-t.i_first).abs()>1).sum(),' 20% mismatch',((t.wb20-t.i_second).abs()>1).sum(), ' wb10 null',t.wb10.isna().sum(),' wb20 null',t.wb20.isna().sum())
print(t[(t.wb10-t.i_first).abs()>1][['proj','key','wb10','i_first','wb20','i_second','sale_price','n_inst']].head(15))
for k in [('BR1','408'),('BR2','106')]:
    print(k); print(inst[(inst.proj==k[0])&(inst.key==k[1])][['sequence','name','state','due_date','amount','percentage']])
    print(s[(s.proj==k[0])&(s.key==k[1])][['Sold Price (AED)','Total Price (AED)','Admin Fee (AED)','10% Amount (AED)','20% Amount (AED)','Amount Collected (AED)','sale_price','inst_sum','notes']].T)
print('contract_date vs SPA/reservation: null contract_date',s.contract_date.isna().sum())
s['resv']=pd.to_datetime(s['Reservation Date'],errors='coerce'); s['cd']=pd.to_datetime(s.contract_date)
print('resv<>contract_date', ((s.resv.dt.date!=s.cd.dt.date)&s.resv.notna()).sum(),'resv null',s.resv.isna().sum())
