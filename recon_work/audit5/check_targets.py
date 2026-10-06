# -*- coding: utf-8 -*-
import pandas as pd, re
M={'PGV':'GOLF','PBR1':'BR1','PBR2':'BR2','PRY':'RES'}
wb=pd.read_excel('C:/Parkgroup Data/Consolidated_Sales_Workbook (4).xlsx',sheet_name='All Units',header=5).iloc[:,1:]
wb=wb[wb['Project Name'].isin(M)].copy()
def key(v):
    s=str(v).strip(); s=re.sub(r'^Unit\s+','',s)
    if re.fullmatch(r'\d+\.0',s): s=s[:-2]
    return s
wb['proj']=wb['Project Name'].map(M); wb['key']=wb['Unit No'].map(key)
targets=[('BR1','608'),('BR1','612'),('BR1','601'),('BR1','701'),('BR1','711'),('BR1','606'),('BR1','610'),
         ('BR1','603'),('BR1','503'),('BR1','508'),('BR1','505'),('BR1','404'),('RES','211'),('RES','404'),
         ('RES','418'),('RES','317'),('RES','318'),('GOLF','302'),('GOLF','R01'),('BR2','206'),('BR2','414'),
         ('BR2','601'),('BR2','309'),('BR2','606'),('BR2','410'),('BR1','101'),('BR1','105'),('BR1','201'),
         ('BR1','212'),('BR1','406'),('BR1','102'),('BR1','107')]
for p,k in targets:
    r=wb[(wb.proj==p)&(wb.key==k)]
    if len(r):
        v=r.iloc[0]
        print(f"{p}/{k}: client={str(v['Client Name'])!r} phone={str(v['Contact No'])!r} email={str(v['Email'])!r}")
    else:
        print(f'{p}/{k}: NOT IN WB')
