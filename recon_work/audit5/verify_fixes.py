# -*- coding: utf-8 -*-
"""Post-fix verification: re-pull phone/email for all sold units' partners and re-diff vs WB(4)."""
import pandas as pd, re, subprocess, base64, io
M={'PGV':'GOLF','PBR1':'BR1','PBR2':'BR2','PRY':'RES'}
wb=pd.read_excel('C:/Parkgroup Data/Consolidated_Sales_Workbook (4).xlsx',sheet_name='All Units',header=5).iloc[:,1:]
wb=wb[wb['Project Name'].isin(M)].copy()
def key(v):
    s=str(v).strip(); s=re.sub(r'^Unit\s+','',s)
    if re.fullmatch(r'\d+\.0',s): s=s[:-2]
    return s
wb['proj']=wb['Project Name'].map(M); wb['key']=wb['Unit No'].map(key)
sold=wb[wb.Status.astype(str).str.lower().str.contains('sold')].copy()

sql=("select pr.code, d.unit_number, p.name, p.phone, p.email from sale_contract c "
     "join property_details d on d.id=c.property_id join property_project pr on pr.id=d.project_id "
     "join res_partner p on p.id=c.buyer_id order by 1,2")
copycmd='COPY (%s) TO STDOUT WITH CSV HEADER' % sql
script='docker exec sgc_rent_mt_db psql -U odoo_mt -d sgc_mt_parkgroup -c "%s"\n' % copycmd
b64=base64.b64encode(script.encode()).decode()
out=subprocess.run(['ssh','-o','ConnectTimeout=15','vps-root','echo %s | base64 -d | bash' % b64],
                   capture_output=True, text=True)
if out.returncode!=0:
    print('SSH ERR', out.stderr); raise SystemExit(1)
print('stdout bytes:', len(out.stdout.encode('utf-8','replace')), 'first:', repr(out.stdout[:120]))
print('stderr:', out.stderr[:300])
db=pd.read_csv(io.StringIO(out.stdout), dtype=str)
db=db.rename(columns={'code':'proj'})
db['key']=db.unit_number.map(key)
db=db[db.proj.isin(M.values())]
print('db rows:', len(db), 'sold rows:', len(sold))
mg=sold.merge(db,on=['proj','key'],how='inner')
print('merged rows:', len(mg))
def nd(v): return re.sub(r'\D','',str(v))
mg['pn']=mg['Contact No'].map(nd); mg['dpn']=mg.phone.map(nd)
pm=mg[mg.pn!=mg.dpn]
print('PHONE mismatches remaining:', len(pm))
print(pm[['proj','key','Contact No','phone']].to_string())
e1=mg.Email.astype(str).str.strip().str.lower(); e2=mg.email.astype(str).str.strip().str.lower()
em=mg[(e1!=e2)&~((e1.isin(['','nan']))&(e2.isin(['','nan'])))]
print('EMAIL mismatches remaining:', len(em))
print(em[['proj','key','Email','email']].to_string())
