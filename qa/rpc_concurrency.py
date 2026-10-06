"""Business-rule concurrency test over JSON-RPC: double clear of one cheque, duplicate cheques, parallel
creation, double approval of one broker. The admin user must be in the PDC and Broker manager groups.

    QA_BASE=... QA_DB=... QA_ADMIN_PASSWORD=... python3 rpc_concurrency.py
"""
import requests, json, base64, random, time, subprocess
from concurrent.futures import ThreadPoolExecutor
import os
BASE=os.environ.get('QA_BASE','http://localhost:8070'); DB=os.environ.get('QA_DB','qa')
PSQL=os.environ.get('QA_PSQL','psql -h /tmp -p 5433').split()
ADMIN_PW=os.environ.get('QA_ADMIN_PASSWORD','admin')
def psql(sql): return subprocess.run(PSQL+['-d',DB,'-Atc',sql],capture_output=True,text=True).stdout.strip()
def login():
    s=requests.Session()
    r=s.post(BASE+'/web/session/authenticate',json={'jsonrpc':'2.0','params':{'db':DB,'login':'admin','password':ADMIN_PW}},timeout=60).json()
    assert r.get('result',{}).get('uid'), r
    return s
def call(s, model, method, args=None, kwargs=None):
    r=s.post(BASE+'/web/dataset/call_kw/%s/%s'%(model,method),json={'jsonrpc':'2.0','method':'call','params':{'model':model,'method':method,'args':args or [],'kwargs':kwargs or {}}},timeout=300).json()
    return r
S=login()
journal=call(S,'account.journal','search',[[['type','=','bank']]],{'limit':1})['result'][0]

print('=== A) PDC: 8 users click "Mark Cleared" on the SAME cheque at once')
partner=call(S,'res.partner','create',[{'name':'Race Party'}])['result']
chq=call(S,'sgc.pdc.cheque','create',[{'partner_id':partner,'cheque_number':'RACE1','bank_name':'B','cheque_date':'2026-10-01','amount':777,'journal_id':journal}])['result']
call(S,'sgc.pdc.cheque','action_register',[[chq]]); call(S,'sgc.pdc.cheque','action_deposit',[[chq]])
def clear(i):
    s=login(); r=call(s,'sgc.pdc.cheque','action_clear',[[chq]])
    return 'ok' if 'result' in r else (r['error']['data']['name'].split('.')[-1] if 'error' in r else '?')
with ThreadPoolExecutor(8) as ex: out=list(ex.map(clear,range(8)))
print('   call outcomes:',{o:out.count(o) for o in set(out)})
print('   payments posted for this cheque:',psql("select count(*) from account_payment p join account_move m on m.id=p.move_id where m.ref like '%%PDC%%' and p.amount=777 and p.partner_id=%d"%partner),'(must be 1)')
print('   cheque state:',psql("select state from sgc_pdc_cheque where id=%d"%chq))

print('=== B) PDC: 10 users create the SAME cheque number/bank/party at once (unique rule)')
def mk(i):
    s=login(); r=call(s,'sgc.pdc.cheque','create',[{'partner_id':partner,'cheque_number':'DUP9','bank_name':'B','cheque_date':'2026-12-01','amount':50}])
    return 'created' if 'result' in r else 'refused'
with ThreadPoolExecutor(10) as ex: out=list(ex.map(mk,range(10)))
print('   outcomes:',{o:out.count(o) for o in set(out)},'| rows in DB:',psql("select count(*) from sgc_pdc_cheque where cheque_number='DUP9'"),'(must be 1)')

print('=== C) PDC: 400 cheques created by 20 concurrent users')
t=time.time()
def bulk(i):
    s=login(); n=0
    for j in range(20):
        r=call(s,'sgc.pdc.cheque','create',[{'partner_id':partner,'cheque_number':'BULK%d_%d'%(i,j),'bank_name':'B','cheque_date':'2026-11-01','amount':10+j}])
        n+= 'result' in r
    return n
with ThreadPoolExecutor(20) as ex: made=sum(ex.map(bulk,range(20)))
print('   created %d/400 in %.1fs | distinct sequence names: %s'%(made,time.time()-t,psql("select count(distinct name)||' of '||count(*) from sgc_pdc_cheque where cheque_number like 'BULK%'")))

print('=== D) BROKER: 6 officers approve the SAME application at once')
pdf=base64.b64encode(b'%PDF-1.4\n%%EOF').decode()
app=call(S,'sgc.broker.application','create',[{'applicant_type':'company','emirate':'dubai','company_name':'Race Realty','full_name':'Racer','email':'racer@stress.test','phone':'+971501234567','trade_license_no':'TLR','trade_license_expiry':'2027-12-31','orn':'55555','emirates_id':'784-1990-1234567-1','signatory_name':'Racer','email_verified':True,'state':'submitted'}])['result']
types=call(S,'sgc.broker.document.type','search_read',[[['required','=',True],['applicant_type','in',['both','company']]]],{'fields':['id','has_expiry']})['result']
for t in types:
    call(S,'sgc.broker.application.document','create',[{'application_id':app,'type_id':t['id'],'file':pdf,'filename':'d.pdf','state':'accepted','expiry_date':'2027-12-31' if t['has_expiry'] else False}])
def appr(i):
    s=login(); r=call(s,'sgc.broker.application','action_approve',[[app]])
    return 'ok' if 'result' in r else (r['error']['data']['name'].split('.')[-1] if 'error' in r else 'weird:'+json.dumps(r)[:150])
with ThreadPoolExecutor(6) as ex: out=list(ex.map(appr,range(6)))
print('   outcomes:',{o:out.count(o) for o in set(out)})
print('   contacts named "Race Realty":',psql("select count(*) from res_partner where name='Race Realty'"),'(must be 1) | trackers:',psql("select count(*) from sgc_broker_expiry_tracker where application_id=%d"%app),'| attachments on contact:',psql("select count(*) from ir_attachment a join res_partner p on p.id=a.res_id and a.res_model='res.partner' where p.name='Race Realty'"))
