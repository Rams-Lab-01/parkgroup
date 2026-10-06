"""Bulk-data stress, run inside `odoo shell` (it rolls back at the end):

    odoo shell -c odoo.conf -d <db> < orm_bulk.py

Creates 5000 cheques and 300 fully approved brokers and prints timings, memory and duplicate checks.
"""
import time, base64, resource
from datetime import timedelta
from odoo import fields

def T(label, t0):
    print('%-58s %6.1fs   (rss %d MB)' % (label, time.time() - t0, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024))

today = fields.Date.context_today(env['res.partner'])
env['res.users'].browse(2).write({'email': 'admin@example.com'})
journal = env['account.journal'].search([('type', '=', 'bank')], limit=1)

# ---------------- PDC ----------------
partners = env['res.partner'].create([{'name': 'PDC Party %d' % i} for i in range(200)])
N = 5000
t = time.time()
vals = [{'partner_id': partners[i % 200].id, 'cheque_number': 'S%06d' % i, 'bank_name': 'B%d' % (i % 7),
         'cheque_date': today + timedelta(days=(i % 40) - 10), 'amount': 100 + i % 900,
         'journal_id': journal.id, 'direction': 'inbound' if i % 3 else 'outbound'} for i in range(N)]
Cheque = env['sgc.pdc.cheque']
chunks = [vals[i:i + 500] for i in range(0, N, 500)]
cheques = Cheque
for c in chunks:
    cheques |= Cheque.create(c)
T('PDC: create %d cheques' % N, t)
t = time.time(); cheques.action_register(); T('PDC: register %d' % N, t)
t = time.time(); n = Cheque.search_count([('maturity_status', '=', 'matured')]); T('PDC: search maturity=matured -> %d rows' % n, t)
t = time.time(); n2 = len(Cheque.search([('maturity_status', '=', 'upcoming'), ('cheque_date', '<=', today + timedelta(days=7))])); T('PDC: search upcoming<=7d -> %d rows' % n2, t)
t = time.time(); rows = Cheque._read_group([('state', '=', 'registered')], ['partner_id'], ['amount:sum']); T('PDC: group by partner (%d groups)' % len(rows), t)
t = time.time(); Cheque._cron_notify_cheques(); T('PDC: notification cron over %d cheques' % N, t)
print('   mails queued:', env['mail.mail'].search_count([('subject', 'ilike', 'cheque')]), '| activities:', env['mail.activity'].search_count([('res_model', '=', 'sgc.pdc.cheque')]))
t = time.time(); Cheque._cron_notify_cheques(); T('PDC: 2nd cron run (must be ~no-op)', t)
print('   mails after 2nd run:', env['mail.mail'].search_count([('subject', 'ilike', 'cheque')]))
sample = cheques.filtered(lambda c: c.direction == 'inbound')[:300]
t = time.time()
for c in sample:
    c.action_clear()
T('PDC: clear 300 cheques (posts 300 payments)', t)
print('   payments created:', len(sample.payment_id), '| all cleared:', all(c.state == 'cleared' for c in sample))
env.cr.rollback()

# ---------------- Broker ----------------
env.invalidate_all()
App = env['sgc.broker.application']
types = env['sgc.broker.document.type'].search([])
pdf = base64.b64encode(b'%PDF-1.4\n%%EOF')
B = 300
t = time.time()
apps = App
for i in range(B):
    app = App.create({'applicant_type': 'company', 'emirate': 'dubai', 'company_name': 'Bulk Realty %d' % i,
        'full_name': 'Owner %d' % i, 'email': 'bulk%d@stress.test' % i, 'phone': '+971501234%03d' % (i % 1000),
        'trade_license_no': 'TL%d' % i, 'trade_license_expiry': today + timedelta(days=(i % 60) - 10),
        'orn': str(10000 + i), 'emirates_id': '784-1990-1234567-1', 'signatory_name': 'Owner %d' % i,
        'vat_trn': '100%012d' % i, 'iban': 'AE070331234567890123456', 'email_verified': True, 'state': 'submitted'})
    for dt in app._required_types():
        env['sgc.broker.application.document'].create({'application_id': app.id, 'type_id': dt.id,
            'file': pdf, 'filename': 'd.pdf', 'state': 'accepted',
            'expiry_date': (today + timedelta(days=(i % 90) - 20)) if dt.has_expiry else False})
    apps |= app
T('Broker: create %d complete applications (%d docs)' % (B, len(apps.document_ids)), t)
t = time.time()
for app in apps:
    app.action_approve()
T('Broker: approve %d (partner + bank + attachments)' % B, t)
print('   partners mapped:', len(apps.partner_id), '| trackers:', env['sgc.broker.expiry.tracker'].search_count([('application_id', 'in', apps.ids)]))
t = time.time(); App._cron_check_expiries(); T('Broker: expiry cron over %d registered brokers' % B, t)
print('   reminder mails:', env['mail.mail'].search_count([('subject', 'ilike', 'Reminder:')]) + env['mail.mail'].search_count([('subject', 'ilike', 'EXPIRED:')]),
      '| expired contacts:', env['res.partner'].search_count([('sgc_broker_status', '=', 'expired')]))
t = time.time(); App._cron_check_expiries(); T('Broker: 2nd cron run same day (no duplicates)', t)
print('   reminder mails after 2nd run:', env['mail.mail'].search_count([('subject', 'ilike', 'Reminder:')]) + env['mail.mail'].search_count([('subject', 'ilike', 'EXPIRED:')]))
t = time.time(); n = env['sgc.broker.expiry.tracker'].search_count([('expiry_date', '<', today)]); T('Broker: expiry monitor query (%d expired items)' % n, t)
env.cr.rollback()
