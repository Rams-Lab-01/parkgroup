"""Broker portal stress / abuse test (HTTP). Needs: requests, psql access to the DB, Odoo running with
several workers and the system parameter sgc_broker.max_registrations_per_ip_hour set high (e.g. 100000)
so that the load test is not stopped by the per-IP limit.

    QA_BASE=http://localhost:8070 QA_DB=mydb QA_PSQL="psql -h /tmp -p 5433" python3 portal_stress.py
"""
import re, time, random, statistics, subprocess, threading, sys, json
from concurrent.futures import ThreadPoolExecutor
import requests

import os
BASE = os.environ.get('QA_BASE', 'http://localhost:8070')
DB = os.environ.get('QA_DB', 'qa')
PSQL = os.environ.get('QA_PSQL', 'psql -h /tmp -p 5433').split()
PDF = b'%PDF-1.4\n' + b'0' * 64 + b'\n%%EOF'

def psql(sql):
    return subprocess.run(PSQL + ['-d', DB, '-Atc', sql], capture_output=True, text=True).stdout.strip()

def sess(ip):
    s = requests.Session()
    s.headers['X-Forwarded-For'] = ip
    return s

def csrf(s, url='/broker/register'):
    r = s.get(BASE + url, timeout=60)
    m = re.search(r'name="csrf_token"\s+value="([^"]+)"', r.text)
    return m.group(1) if m else None

def register(email, ip, **over):
    s = sess(ip)
    data = {'applicant_type': 'company', 'emirate': 'dubai', 'company_name': 'Stress Co', 'full_name': 'Stress Tester',
            'email': email, 'phone': '+971501234567', 'csrf_token': csrf(s)}
    data.update(over)
    t = time.time()
    r = s.post(BASE + '/broker/register/submit', data=data, allow_redirects=False, timeout=120)
    return s, r, time.time() - t

def pct(xs, p):
    xs = sorted(xs); return xs[min(int(len(xs) * p), len(xs) - 1)]

print('=== 1) THROUGHPUT: 120 registrations, 16 threads, distinct IPs')
emails = ['load%d@stress.test' % i for i in range(120)]
t0 = time.time()
with ThreadPoolExecutor(16) as ex:
    res = list(ex.map(lambda i: register(emails[i], '10.1.%d.%d' % (i // 250, i % 250 + 1)), range(120)))
dur = time.time() - t0
codes = [r.status_code for _, r, _ in res]; lat = [l for _, _, l in res]
print('   %d req in %.1fs = %.1f req/s | status %s | p50 %.2fs p95 %.2fs max %.2fs' % (
    len(res), dur, len(res) / dur, {c: codes.count(c) for c in set(codes)}, pct(lat, .5), pct(lat, .95), max(lat)))
print('   applications in DB:', psql("select count(*) from sgc_broker_application where email like 'load%@stress.test'"),
      '| verification mails queued:', psql("select count(*) from mail_mail where email_to like 'load%@stress.test'"))

print('=== 3) RACE: 30 concurrent registrations, SAME email, distinct IPs')
with ThreadPoolExecutor(30) as ex:
    res = list(ex.map(lambda i: register('race@stress.test', '10.2.0.%d' % (i + 1)), range(30)))
print('   status codes:', {c: [r.status_code for _, r, _ in res].count(c) for c in set(r.status_code for _, r, _ in res)})
print('   applications created for that email:', psql("select count(*) from sgc_broker_application where email='race@stress.test'"), '(expected 1)')

print('=== 4) BRUTE FORCE: 200 concurrent wrong codes on ONE application')
s, r, _ = register('brute@stress.test', '10.3.0.1')
tok = re.search(r'/broker/verify/([^"/ ]+)', r.headers['Location']).group(1)
code = re.search(r'>(\d{6})<', psql("select body_html from mail_mail where email_to like '%brute@stress.test%' order by id desc limit 1")).group(1)
wrong = '000000' if code != '000000' else '111111'
def guess(i):
    ss = sess('10.3.1.%d' % (i % 250 + 1)); tkn = csrf(ss, '/broker/verify/' + tok)
    rr = ss.post(BASE + '/broker/verify/%s/check' % tok, data={'code': wrong, 'csrf_token': tkn}, timeout=120)
    return 'not correct' in rr.text, 'Too many wrong' in rr.text
with ThreadPoolExecutor(25) as ex:
    out = list(ex.map(guess, range(200)))
bad = sum(1 for b, _ in out if b); locked = sum(1 for _, l in out if l)
print('   responses "code not correct" (= a real guess was evaluated): %d | "locked": %d | max allowed guesses: 5' % (bad, locked))
print('   attempts counter in DB:', psql("select code_attempts from sgc_broker_application where email='brute@stress.test'"))
ss = sess('10.3.2.1'); tkn = csrf(ss, '/broker/verify/' + tok)
rr = ss.post(BASE + '/broker/verify/%s/check' % tok, data={'code': code, 'csrf_token': tkn}, timeout=60)
print('   CORRECT code after lockout accepted?', 'application' in rr.url, '(must be False)')

print('=== 5) FUZZ / ABUSE inputs on registration (expect no 500, no reflected raw script)')
payloads = {
    'xss_name': {'full_name': '<script>alert(1)</script>"><img src=x onerror=alert(2)>'},
    'xss_company': {'company_name': "</title><svg onload=alert(3)>"},
    'sqli_email': {'email': "a'; DROP TABLE res_partner;--@x.com"},
    'sqli_name': {'full_name': "Robert'); DROP TABLE sgc_broker_application;--"},
    'huge_name_50k': {'full_name': 'A' * 50000},
    'huge_address_200k': {'street': 'B' * 200000},
    'null_byte': {'full_name': 'Bad\x00Name'},
    'emoji_rtl': {'full_name': 'مرحبا 😀 عبدالله', 'company_name': 'شركة العقارات 🏢'},
    'bad_emirate': {'emirate': "dubai' OR 1=1--"},
    'bad_type': {'applicant_type': 'admin'},
    'bad_nationality': {'nationality_id': "1 OR 1=1"},
    'newline_inject_email': {'email': 'a@b.com\r\nBcc: evil@x.com'},
}
fails = []
for i, (name, over) in enumerate(payloads.items()):
    over = dict(over); over.setdefault('email', 'fuzz%d@stress.test' % i)
    try:
        s, r, dt = register(over.pop('email'), '10.4.0.%d' % (i + 1), **over)
        body = r.text if r.status_code == 200 else ''
        raw = '<script>alert' in body or 'onerror=alert' in body or 'onload=alert' in body
        print('   %-22s -> HTTP %s %.2fs%s' % (name, r.status_code, dt, '  RAW SCRIPT REFLECTED!' if raw else ''))
        if r.status_code >= 500 or raw: fails.append(name)
    except Exception as e:
        print('   %-22s -> EXC %s' % (name, e)); fails.append(name)
print('   stored with huge/odd values (len>300):', psql("select count(*) from sgc_broker_application where length(full_name)>300 or length(street)>300"))
print('   injection-created apps with newline in email:', psql("select count(*) from sgc_broker_application where email like E'%\\n%'"))
print('   FUZZ FAILURES:', fails or 'none')
print('   tables intact:', psql("select count(*) from res_partner") != '' and psql("select count(*) from sgc_broker_application") != '')

print('=== 6) UPLOAD STRESS')
s6, r6, _ = register('upload@stress.test', '10.6.0.1')
tok6 = re.search(r'/broker/verify/([^"/ ]+)', r6.headers['Location']).group(1)
code6 = re.search(r'>(\d{6})<', psql("select body_html from mail_mail where email_to like '%upload@stress.test%' order by id desc limit 1")).group(1)
tkn = csrf(s6, '/broker/verify/' + tok6)
s6.post(BASE + '/broker/verify/%s/check' % tok6, data={'code': code6, 'csrf_token': tkn}, timeout=60)
type_id = psql("select id from sgc_broker_document_type where code='moa'")
def up(content, name, s=None):
    s = s or sess('10.6.%d.%d' % (random.randint(1, 200), random.randint(1, 200)))
    tk = csrf(s, '/broker/application/' + tok6)
    t = time.time()
    r = s.post(BASE + '/broker/application/%s/upload' % tok6, data={'type_id': type_id, 'csrf_token': tk},
               files={'file': (name, content)}, timeout=300)
    return r, time.time() - t
big_ok = b'%PDF-1.4\n' + b'0' * (9 * 1024 * 1024) + b'\n%%EOF'
t0 = time.time()
with ThreadPoolExecutor(8) as ex:
    res = list(ex.map(lambda i: up(big_ok, 'big%d.pdf' % i), range(8)))
ok = sum(1 for r, _ in res if 'Document uploaded' in r.text); capped = sum(1 for r, _ in res if 'Too many files' in r.text)
print('   8 concurrent 9 MB uploads in %.1fs: accepted %d, refused-by-cap %d (per-type cap 5), 5xx: %d' % (
    time.time() - t0, ok, capped, sum(1 for r, _ in res if r.status_code >= 500)))
too_big = b'%PDF-1.4\n' + b'0' * (11 * 1024 * 1024)
r, dt = up(too_big, 'toobig.pdf'); print('   11 MB file: refused=%s in %.1fs, HTTP %s' % ('too large' in r.text, dt, r.status_code))
r, dt = up(b'%PDF-1.4' + b'0' * (60 * 1024 * 1024), 'huge.pdf'); print('   60 MB file: refused=%s in %.1fs, HTTP %s' % ('too large' in r.text, dt, r.status_code))
type_id = psql("select id from sgc_broker_document_type where code='goaml'")
print('   --- filename abuse (on a type with free slots) ---')
for name, content in (('../../etc/passwd.pdf', PDF), ('a\x00b.pdf', PDF), ('x.pdf.exe', PDF), ('script.html', b'<script>'), ('noext', PDF), ('UPPER.PDF', PDF)):
    r, dt = up(content, name)
    print('   filename %-22r -> HTTP %s: %s' % (name, r.status_code, 'accepted' if 'Document uploaded' in r.text else ('refused' if 'alert-danger' in r.text else '??')))
print('   stored filenames:', psql("select string_agg(filename, ' | ') from sgc_broker_application_document d join sgc_broker_application a on a.id=d.application_id where a.email='upload@stress.test'"))
print('   server alive & worker memory OK:', requests.get(BASE + '/broker/register', timeout=30).status_code == 200)
