import base64
import re
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, tagged

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
EXE = b'MZ\x90\x00' + b'\x00' * 32
GOOD_IBAN = 'AE070331234567890123456'


@tagged('post_install', '-at_install')
class TestBrokerPortalFlow(HttpCase):

    def setUp(self):
        super().setUp()
        self.Application = self.env['sgc.broker.application']
        self.officer = self.env['res.users'].create({
            'name': 'Compliance Officer', 'login': 'officer1', 'email': 'officer@example.com',
            'group_ids': [(6, 0, [self.env.ref('sgc_broker_registration.group_broker_manager').id])]})

    # -- helpers --------------------------------------------------------
    def _csrf(self, url='/broker/register'):
        html = self.url_open(url).text
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
        self.assertTrue(match, 'no csrf token on %s' % url)
        return match.group(1)

    def _post(self, url, data, csrf_url, files=None):
        data = dict(data, csrf_token=self._csrf(csrf_url))
        return self.url_open(url, data=data, files=files)

    def _register(self, **over):
        data = {'applicant_type': 'company', 'emirate': 'dubai', 'company_name': 'Acme Brokers LLC',
                'full_name': 'Jane Broker', 'email': 'jane@acme.test', 'phone': '+971 50 123 4567',
                'street': 'Business Bay', 'city': 'Dubai'}
        data.update(over)
        return self._post('/broker/register/submit', data, '/broker/register')

    def _last_code(self, email):
        mail = self.env['mail.mail'].search([('email_to', 'ilike', email),
                                             ('subject', 'ilike', 'verification code')], order='id desc', limit=1)
        self.assertTrue(mail, 'no verification mail queued')
        return re.search(r'>(\d{6})<', mail.body_html).group(1)

    def _mail_for(self, subject_part, email):
        mails = self.env['mail.mail'].search([('subject', 'ilike', subject_part)])
        return mails.filtered(lambda m: email in (m.email_to or '') or email in m.recipient_ids.mapped('email'))

    def _verified_app(self, **over):
        self._register(**over)
        app = self.Application.search([('email', '=', over.get('email', 'jane@acme.test'))])
        self.assertEqual(len(app), 1)
        self._post('/broker/verify/%s/check' % app.access_token,
                   {'code': self._last_code(app.email)}, '/broker/verify/%s' % app.access_token)
        app.invalidate_recordset()
        return app

    def _details(self, app, **over):
        data = {'company_name': 'Acme Brokers LLC', 'full_name': 'Jane Broker', 'phone': '+971501234567',
                'emirates_id': '784-1990-1234567-1', 'trade_license_no': 'TL-998',
                'trade_license_authority': 'DET', 'trade_license_expiry': str(fields.Date.today() + timedelta(days=300)),
                'orn': '12345', 'signatory_name': 'Jane Broker', 'signatory_title': 'Manager',
                'goaml_id': 'G-1', 'vat_trn': '100123456789012', 'iban': GOOD_IBAN, 'bank_name': 'ENBD',
                'account_holder': 'Acme Brokers LLC'}
        data.update(over)
        return self._post('/broker/application/%s/details' % app.access_token, data,
                          '/broker/application/%s' % app.access_token)

    def _upload(self, app, dtype, content=PDF, name='doc.pdf', expiry=True):
        data = {'type_id': dtype.id}
        if dtype.has_expiry and expiry:
            data['expiry_date'] = str(fields.Date.today() + timedelta(days=200))
        return self._post('/broker/application/%s/upload' % app.access_token, data,
                          '/broker/application/%s' % app.access_token,
                          files={'file': (name, content)})

    def _upload_all_required(self, app):
        app.invalidate_recordset()
        for dtype in app._required_types():
            self._upload(app, dtype)
        app.invalidate_recordset()

    def _submit(self, app, **over):
        data = {'accept_terms': '1', 'accept_aml': '1', 'accept_accuracy': '1', 'declared_name': 'Jane Broker'}
        data.update(over)
        return self._post('/broker/application/%s/submit' % app.access_token, data,
                          '/broker/application/%s' % app.access_token)

    # -- tests ----------------------------------------------------------
    def test_pages_render(self):
        self.assertEqual(self.url_open('/broker/register').status_code, 200)
        self.assertEqual(self.url_open('/broker/application/not-a-token').status_code, 404)
        self.assertEqual(self.url_open('/broker/verify/not-a-token').status_code, 404)

    def test_register_creates_unverified_application_and_sends_code(self):
        res = self._register()
        self.assertEqual(res.status_code, 200)
        app = self.Application.search([('email', '=', 'jane@acme.test')])
        self.assertEqual(app.state, 'draft')
        self.assertFalse(app.email_verified)
        self.assertEqual(app.phone, '+971501234567')
        self.assertTrue(re.fullmatch(r'\d{6}', self._last_code('jane@acme.test')))
        self.assertNotIn(self._last_code('jane@acme.test'), app.code_hash or '')   # only a hash is stored

    def test_invalid_input_is_rejected_with_message(self):
        for over, msg in (({'email': 'bad'}, 'valid email'), ({'phone': '12'}, 'digits'),
                          ({'emirate': 'mars'}, 'emirate')):
            res = self._register(**over)
            self.assertIn(msg, res.text)
        self.assertFalse(self.Application.search([('email', '=', 'jane@acme.test')]))

    def test_honeypot_blocks_bots(self):
        self._register(website_hp='http://spam')
        self.assertFalse(self.Application.search([('email', '=', 'jane@acme.test')]))

    def test_code_verification_rules(self):
        self._register()
        app = self.Application.search([('email', '=', 'jane@acme.test')])
        good = self._last_code(app.email)
        wrong = '000000' if good != '000000' else '111111'
        self.assertEqual(app.verify_code(wrong), 'bad')
        self.assertFalse(app.email_verified)
        app.code_expiry = fields.Datetime.now() - timedelta(minutes=1)
        self.assertEqual(app.verify_code(good), 'expired')
        app.write({'code_expiry': fields.Datetime.now() + timedelta(minutes=5), 'code_attempts': 4})
        self.assertEqual(app.verify_code(wrong), 'locked')
        self.assertEqual(app.verify_code(good), 'locked')           # locked until a new code is requested
        app.code_last_sent = fields.Datetime.now() - timedelta(minutes=5)
        self.assertEqual(app.action_send_code()[0], 'ok')
        self.assertEqual(app.verify_code(self._last_code(app.email)), 'ok')
        self.assertTrue(app.email_verified)
        self.assertEqual(app.state, 'verified')

    def test_resend_cooldown_and_hourly_limit(self):
        self._register()
        app = self.Application.search([('email', '=', 'jane@acme.test')])
        status, wait = app.action_send_code()
        self.assertEqual(status, 'cooldown')
        self.assertGreater(wait, 0)
        for _i in range(4):
            app.code_last_sent = fields.Datetime.now() - timedelta(minutes=2)
            self.assertEqual(app.action_send_code()[0], 'ok')
        app.code_last_sent = fields.Datetime.now() - timedelta(minutes=2)
        self.assertEqual(app.action_send_code()[0], 'limit')

    def test_duplicate_email_does_not_leak_token_or_duplicate(self):
        self._register()
        res = self._register()
        self.assertIn('Check your inbox', res.text)
        self.assertEqual(self.Application.search_count([('email', '=', 'jane@acme.test')]), 1)
        app = self.Application.search([('email', '=', 'jane@acme.test')])
        self.assertNotIn(app.access_token, res.text)

    def test_unverified_cannot_reach_application_page(self):
        self._register()
        app = self.Application.search([('email', '=', 'jane@acme.test')])
        res = self.url_open('/broker/application/%s' % app.access_token, allow_redirects=False)
        self.assertIn(res.status_code, (301, 302, 303))
        self.assertIn('/broker/verify/', res.headers['Location'])

    def test_application_page_shows_working_controls(self):
        app = self._verified_app()
        html = self.url_open('/broker/application/%s' % app.access_token).text
        self.assertIn('/broker/application/%s/upload' % app.access_token, html)
        self.assertIn('Submit application', html)
        self.assertIn('Save details', html)
        self.assertNotIn('disabled="disabled"', html)

    def test_upload_validation(self):
        app = self._verified_app()
        trade = self.env.ref('sgc_broker_registration.doctype_trade_license')
        for content, name, msg in ((EXE, 'x.exe', 'Only PDF'), (EXE, 'fake.pdf', 'does not match'),
                                   (b'', 'empty.pdf', 'empty')):
            res = self._upload(app, trade, content=content, name=name)
            self.assertIn(msg, res.text)
        res = self._upload(app, trade, expiry=False)
        self.assertIn('expiry date', res.text)
        self.assertFalse(app.document_ids)
        # an expired document is refused
        res = self._post('/broker/application/%s/upload' % app.access_token,
                         {'type_id': trade.id, 'expiry_date': str(fields.Date.today() - timedelta(days=1))},
                         '/broker/application/%s' % app.access_token, files={'file': ('a.pdf', PDF)})
        self.assertIn('expired', res.text)
        self.assertFalse(app.document_ids)
        self._upload(app, trade)
        self.assertEqual(len(app.document_ids), 1)
        # an individual-only document is not offered to a company
        passport = self.env.ref('sgc_broker_registration.doctype_passport')
        self.assertIn('Unknown document', self._upload(app, passport, name='p.pdf').text)

    def test_cannot_submit_until_complete_then_full_review_and_mapping(self):
        app = self._verified_app()
        res = self._submit(app)
        self.assertIn('Missing required document', res.text)
        self.assertEqual(app.state, 'verified')

        self._details(app)
        app.invalidate_recordset()
        self.assertEqual(app.iban, GOOD_IBAN)
        self.assertEqual(app.emirates_id, '784-1990-1234567-1')
        self._upload_all_required(app)
        self.assertTrue(app.docs_complete)

        self.assertIn('declarations', self._submit(app, accept_aml='').text)
        self.assertIn('electronic signature', self._submit(app, declared_name='').text)
        self.assertEqual(app.state, 'verified')

        self._submit(app)
        app.invalidate_recordset()
        self.assertEqual(app.state, 'submitted')
        self.assertTrue(app.declared_at)
        self.assertTrue(app.activity_ids, 'officers must get a to-do')
        self.assertTrue(self._mail_for('received', app.email))

        # locked for the applicant now
        self.assertIn('no longer', self._upload(app, app._required_types()[0]).text)

        # review
        app = app.with_user(self.officer)
        with self.assertRaises(UserError):
            app.action_approve()                       # documents not accepted yet
        app.action_start_review()
        app.document_ids.action_accept()
        app.action_approve()
        self.assertEqual(app.state, 'approved')
        partner = app.partner_id
        self.assertTrue(partner.is_company)
        self.assertEqual(partner.name, 'Acme Brokers LLC')
        self.assertEqual(partner.email, 'jane@acme.test')
        self.assertEqual(partner.vat, '100123456789012')
        self.assertTrue(partner.sgc_is_broker)
        self.assertEqual(partner.sgc_broker_orn, '12345')
        self.assertEqual(partner.sgc_trade_license_no, 'TL-998')
        self.assertEqual(partner.sgc_regulator, 'dubai')
        self.assertEqual(partner.sgc_broker_status, 'active')
        self.assertIn('Registered Broker', partner.category_id.mapped('name'))
        self.assertTrue(partner.child_ids.filtered(lambda c: c.name == 'Jane Broker'))
        self.assertTrue(partner.bank_ids.filtered(lambda b: b.sanitized_acc_number == GOOD_IBAN))
        self.assertEqual(len(self.env['ir.attachment'].search([
            ('res_model', '=', 'res.partner'), ('res_id', '=', partner.id)])), len(app.document_ids))
        self.assertTrue(self._mail_for('approved', app.email), 'approval mail missing')

    def test_request_info_then_resubmit_and_reject(self):
        app = self._verified_app()
        self._details(app)
        self._upload_all_required(app)
        self._submit(app)
        app = app.with_user(self.officer)
        app._do_request_info('Trade licence is blurred')
        self.assertEqual(app.state, 'needs_info')
        res = self.url_open('/broker/application/%s' % app.access_token)
        self.assertIn('Trade licence is blurred', res.text)
        self._submit(app)                                   # applicant can fix and resubmit
        self.assertEqual(app.state, 'submitted')
        app._do_reject('Not eligible')
        self.assertEqual(app.state, 'rejected')
        self.assertTrue(self._mail_for('decision', app.email))
        # a rejected applicant can register again
        self.assertNotIn('Check your inbox', self._register().text)

    def test_individual_requirements_and_existing_contact_is_reused(self):
        existing = self.env['res.partner'].create({
            'name': 'Old Jane', 'email': 'solo@acme.test', 'is_company': False})
        app = self._verified_app(applicant_type='individual', company_name='', email='solo@acme.test',
                                 full_name='Solo Broker', emirate='abu_dhabi')
        codes = set(app._required_types().mapped('code'))
        self.assertTrue({'passport', 'emirates_id', 'residence_visa', 'broker_card', 'photo',
                         'bank_letter', 'signed_agreement'} <= codes)
        self.assertNotIn('trade_license', codes)
        self._post('/broker/application/%s/details' % app.access_token,
                   {'full_name': 'Solo Broker', 'emirates_id': '784199012345671', 'passport_no': 'P123',
                    'brn': '45678', 'phone': '0501234567', 'iban': GOOD_IBAN},
                   '/broker/application/%s' % app.access_token)
        self._upload_all_required(app)
        self._submit(app, declared_name='Solo Broker')
        app = app.with_user(self.officer)
        app.document_ids.action_accept()
        app.action_approve()
        self.assertEqual(app.partner_id, existing)
        self.assertEqual(existing.sgc_broker_brn, '45678')
        self.assertFalse(existing.is_company)

    def test_public_cannot_read_applications_directly(self):
        app = self._verified_app()
        public = self.env.ref('base.public_user')
        with self.assertRaises(AccessError):
            self.Application.with_user(public).search([])
        with self.assertRaises(AccessError):
            app.with_user(public).read(['email'])

    def test_expiry_cron_alerts_once_and_flags_partner(self):
        app = self._verified_app()
        self._details(app, trade_license_expiry=str(fields.Date.today() + timedelta(days=300)))
        self._upload_all_required(app)
        self._submit(app)
        app = app.with_user(self.officer)
        app.document_ids.action_accept()
        app.action_approve()
        app.sudo().trade_license_expiry = fields.Date.today() + timedelta(days=10)
        app.sudo().activity_ids.unlink()
        self.Application._cron_check_expiries()
        self.assertTrue(app.sudo().licence_alerted)
        n = len(app.sudo().activity_ids)
        self.assertGreater(n, 0)
        self.Application._cron_check_expiries()
        self.assertEqual(len(app.sudo().activity_ids), n)
        app.sudo().trade_license_expiry = fields.Date.today() - timedelta(days=1)
        self.Application._cron_check_expiries()
        self.assertEqual(app.partner_id.sgc_broker_status, 'expired')

    def test_agreement_report_renders(self):
        app = self._verified_app()
        report = self.env.ref('sgc_broker_registration.action_report_broker_agreement')
        html, _fmt = report._render_qweb_html(report.report_name, app.ids)
        self.assertIn(b'BROKERAGE COOPERATION AGREEMENT', html)
        self.assertIn(b'Acme Brokers LLC', html)
        res = self.url_open('/broker/application/%s/agreement' % app.access_token)
        self.assertEqual(res.status_code, 200)
