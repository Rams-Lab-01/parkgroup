# -*- coding: utf-8 -*-
"""Recon3 contact fixes (2026-10-05 audit) - runs inside `odoo shell`.
Source of truth: Consolidated_Sales_Workbook (4).xlsx 'All Units' (Contact No / Email).
Run: docker exec -i sgc_rent_mt /entrypoint.sh odoo shell -d sgc_mt_parkgroup --no-http --log-level=warn < fix_contacts.py
Dry-run: add -e FIX_DRY=1
Only partners whose current name matches the expected name are touched. Single-contract buyers only.
"""
import os
DRY = os.environ.get('FIX_DRY') == '1'
report = []
def L(m):
    s = str(m); report.append(s); print(s, flush=True)

# partner_id: (expected_partner_name, new_phone, new_email_or_None)
FIXES = {
    901:  ('David,Michel Becu & Danielle,Nadege Ganga', '+33660517016/+33613817928', None),
    904:  ('Edward Campbell Kelly', '+447340871859- +971565779963', None),
    908:  ('Manik Bhatheja / Robin Dhawan', '+0918 8600 03839 / +919717711133', None),
    918:  ('Ivan Todorovic / Dragana Todorovic', '+491704568305 / +381645251642', None),
    936:  ('Ammar Jamal', '+92 3212133315', None),
    963:  ('Prasanna Rangaswamy Mysore', '+1 7327 281 4198', None),
    833:  ('FAHAD SANA UL HAQ \\EMAD SANA UL HAQ\\SAAD SANA UL HAQ', '+971551064857\\+971505679411\\+971506556878', None),
    865:  ('KIM SANDRA NAULLS / Andrew Bines', '+447908841304/+447950599199', None),
    817:  ('Bilal Gulamali', '43 676 9609812', None),
    818:  ('Yvonne Anakaur Musany', '971 50 462 3342', None),
    995:  ('V\u00e1clav Kulich & Jana Vorudova', '420724366621 & 420605981124', 'vasek.kulich@gmail.com'),
    1005: ('Jitka Zieba', '4915223392696 & 971527641750', None),
}

L('DRY=%s db=%s user=%s' % (DRY, env.cr.dbname, env.user.name))
n_upd = n_skip = 0
for pid in sorted(FIXES):
    name, phone, email = FIXES[pid]
    p = env['res.partner'].browse(pid)
    if not p.exists():
        L('!! partner %d missing - skipped' % pid); n_skip += 1; continue
    if p.name != name:
        L('!! partner %d name changed since audit: %r - skipped' % (pid, p.name)); n_skip += 1; continue
    vals = {}
    if (p.phone or '') != phone:
        vals['phone'] = phone
    if email and (p.email or '') != email:
        vals['email'] = email
    if not vals:
        L('partner %d (%s): already matches source' % (pid, name)); continue
    L('partner %d (%s): phone %r -> %r%s' % (pid, name, p.phone or '', phone,
        (' | email %r -> %r' % (p.email or '', email)) if 'email' in vals else ''))
    if not DRY:
        p.write(vals)
    n_upd += 1
if not DRY:
    env.cr.commit()
L('DONE updated=%d skipped=%d' % (n_upd, n_skip))
os.makedirs('/tmp/pg_state', exist_ok=True)
with open('/tmp/pg_state/fix_contacts_%s_report.txt' % env.cr.dbname, 'w', encoding='utf-8') as f:
    f.write('\n'.join(report) + '\n')
L('report -> /tmp/pg_state/fix_contacts_%s_report.txt' % env.cr.dbname)
