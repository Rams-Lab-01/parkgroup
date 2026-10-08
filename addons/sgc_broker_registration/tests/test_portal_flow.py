import re
from datetime import timedelta
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields
from psycopg2 import IntegrityError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger

PDF = b'%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
EXE = b'MZ\x90\x00' + b'\x00' * 32
GOOD_IBAN = 'AE070331234567890123456'


def base64_pdf():
    import base64
    return base64.b64encode(PDF)


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
        data = {'email': 'jane@acme.test'}
        data.update(over)
        return self._post('/broker/register/submit', data, '/broker/register')

    def _last_code(self, email):
        mail = self.env['mail.mail'].search([('email_to', 'ilike', email),
                                             ('subject', 'ilike', 'Verify your email')], order='id desc', limit=1)
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
        data = {'applicant_type': 'company', 'emirate': 'dubai',
                'company_name': 'Acme Brokers LLC', 'full_name': 'Jane Broker', 'phone': '+971501234567',
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
        self.assertFalse(app.phone)
        self.assertTrue(re.fullmatch(r'\d{6}', self._last_code('jane@acme.test')))
        self.assertNotIn(self._last_code('jane@acme.test'), app.code_hash or '')   # only a hash is stored

    def test_invalid_input_is_rejected_with_message(self):
        res = self._register(email='bad')
        self.assertIn('valid email', res.text)
        self.assertFalse(self.Application.search([('email', '=', 'jane@acme.test')]))
        # phone / emirate are validated when the details are provided (after verification)
        app = self._verified_app()
        res = self._post('/broker/application/%s/details' % app.access_token,
                         {'phone': '12'}, '/broker/application/%s' % app.access_token)
        self.assertIn('digits', res.text)
        res = self._post('/broker/application/%s/details' % app.access_token,
                         {'emirate': 'mars'}, '/broker/application/%s' % app.access_token)
        self.assertIn('emirate', res.text)

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
        self.assertIn('Review Application', html)
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
        self.assertEqual(partner.sgc_broker_status, 'registered')
        self.assertEqual(app.agreement_start, fields.Date.today())
        self.assertEqual(app.agreement_expiry, fields.Date.today() + relativedelta(years=1))
        self.assertEqual(partner.sgc_agreement_expiry, app.agreement_expiry)
        self.assertTrue(app.expiry_tracker_ids.filtered(lambda t: t.key == 'agreement'))
        self.assertTrue(app.expiry_tracker_ids.filtered(lambda t: t.key == 'trade_license'))
        self.assertIn('Registered Broker', partner.category_id.mapped('name'))
        self.assertTrue(partner.child_ids.filtered(lambda c: c.name == 'Jane Broker'))
        self.assertTrue(partner.bank_ids.filtered(lambda b: b.sanitized_acc_number == GOOD_IBAN))
        self.assertEqual(len(self.env['ir.attachment'].search([
            ('res_model', '=', 'res.partner'), ('res_id', '=', partner.id)])), len(app.document_ids))
        self.assertTrue(self._mail_for('approved', app.email), 'approval mail missing')

    def test_review_gated_until_complete_then_success_page(self):
        app = self._verified_app()
        res = self.url_open('/broker/application/%s/review' % app.access_token)
        self.assertIn('Complete all required', res.text)
        self._details(app)
        self._upload_all_required(app)
        res = self.url_open('/broker/application/%s/review' % app.access_token)
        self.assertIn('Review your application', res.text)
        self.assertIn('Email Verified', res.text)
        self._submit(app)
        app.invalidate_recordset()
        self.assertEqual(app.state, 'submitted')
        res = self.url_open('/broker/application/%s/thanks' % app.access_token)
        self.assertIn('Application Successfully Submitted', res.text)
        self.assertIn(app.name, res.text)
        self.assertIn('48 hours', res.text)

    def test_duplicate_submission_is_blocked(self):
        app = self._verified_app()
        self._details(app)
        self._upload_all_required(app)
        self._submit(app)
        app.invalidate_recordset()
        res = self._submit(app)
        self.assertIn('no longer', res.text)
        self.assertEqual(self.Application.search_count([('email', '=', 'jane@acme.test')]), 1)

    def test_unverified_user_cannot_open_review_or_submit(self):
        self._register()
        app = self.Application.search([('email', '=', 'jane@acme.test')])
        for url in ('/broker/application/%s/review' % app.access_token,
                    '/broker/application/%s/thanks' % app.access_token,
                    '/broker/application/%s' % app.access_token):
            res = self.url_open(url, allow_redirects=False)
            self.assertIn(res.status_code, (301, 302, 303, 404))
        res = self._post('/broker/application/%s/details' % app.access_token,
                         {'full_name': 'X'}, '/broker/application/%s' % app.access_token)
        self.assertEqual(res.status_code, 404)

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
        app = self._verified_app(email='solo@acme.test')
        self._post('/broker/application/%s/details' % app.access_token,
                   {'applicant_type': 'individual', 'emirate': 'abu_dhabi',
                    'full_name': 'Solo Broker', 'emirates_id': '784199012345671', 'passport_no': 'P123',
                    'brn': '45678', 'phone': '0501234567', 'iban': GOOD_IBAN},
                   '/broker/application/%s' % app.access_token)
        app.invalidate_recordset()
        codes = set(app._required_types().mapped('code'))
        self.assertTrue({'passport', 'emirates_id', 'residence_visa', 'broker_card', 'photo',
                         'bank_letter', 'signed_agreement'} <= codes)
        self.assertNotIn('trade_license', codes)
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

    # -- expiry engine ---------------------------------------------------
    def _registered_app(self):
        app = self._verified_app()
        self._details(app)
        self._upload_all_required(app)
        self._submit(app)
        app = app.with_user(self.officer)
        app.document_ids.action_accept()
        app.action_approve()
        return app

    def _tracker(self, app, key):
        return app.sudo().expiry_tracker_ids.filtered(lambda t: t.key == key)

    def _notices(self, app, label_part):
        mails = self.env['mail.mail'].search([('subject', 'ilike', label_part)])
        return mails.filtered(lambda m: app.email in (m.email_to or ''))

    def test_registered_status_and_one_year_agreement(self):
        app = self._registered_app()
        self.assertEqual(app.state, 'approved')
        self.assertEqual(app.partner_id.sgc_broker_status, 'registered')
        self.assertEqual(app.agreement_expiry, fields.Date.today() + relativedelta(years=1))

    def _on(self, day):
        """Run code as if today were `day` (the cron and all date logic read context_today)."""
        return patch.object(fields.Date, 'context_today', staticmethod(lambda record, timestamp=None: day))

    def test_daily_for_5_days_then_expiry_day_then_every_15_days(self):
        app = self._registered_app()
        expiry = fields.Date.today() + timedelta(days=40)
        app.sudo().trade_license_expiry = expiry
        label = 'Trade licence'
        counts = {}
        for offset in (7, 6, 5, 4, 3, 2, 1):
            with self._on(expiry - timedelta(days=offset)):
                self.Application._cron_check_expiries()
                self.Application._cron_check_expiries()          # a second run the same day adds nothing
            counts[offset] = len(self._notices(app, 'Reminder: %s' % label))
        self.assertEqual(counts, {7: 0, 6: 0, 5: 1, 4: 2, 3: 3, 2: 4, 1: 5}, 'one reminder per day, last 5 days')
        self.assertEqual(app.partner_id.sgc_broker_status, 'registered')

        # expiry date = first day of expiration
        with self._on(expiry):
            self.Application._cron_check_expiries()
        expired = self._notices(app, 'EXPIRED: %s' % label)
        self.assertEqual(len(expired), 1)
        self.assertEqual(app.partner_id.sgc_broker_status, 'expired')
        self.assertEqual(len(self._notices(app, 'Reminder: %s' % label)), 5)

        # afterwards only every 15 days
        for after, total in ((1, 1), (14, 1), (15, 2), (16, 2), (29, 2), (30, 3), (44, 3), (45, 4)):
            with self._on(expiry + timedelta(days=after)):
                self.Application._cron_check_expiries()
            self.assertEqual(len(self._notices(app, 'EXPIRED: %s' % label)), total, 'day +%s' % after)
        # one open to-do per item, never piled up
        self.assertEqual(len(app.sudo().activity_ids.filtered(
            lambda a: a.summary.startswith('[Trade licence]'))), len(app._officers()))

        # renewal restarts everything and the contact is registered again
        app.sudo().trade_license_expiry = fields.Date.today() + timedelta(days=365)
        self.assertEqual(app.partner_id.sgc_broker_status, 'registered')
        self.assertFalse(self._tracker(app, 'trade_license').last_alert_date)
        self.assertFalse(self._tracker(app, 'trade_license').pre_alert_date)

    def test_agreement_reminders_and_renewal(self):
        app = self._registered_app()
        today = fields.Date.today()
        app.sudo().agreement_expiry = today + timedelta(days=3)
        self.Application._cron_check_expiries()
        self.assertEqual(len(self._notices(app, 'Reminder: Brokerage agreement')), 1)
        app.sudo().agreement_expiry = today - timedelta(days=2)
        self.Application._cron_check_expiries()
        self.assertEqual(len(self._notices(app, 'EXPIRED: Brokerage agreement')), 1)
        self.assertEqual(app.partner_id.sgc_broker_status, 'expired')
        app.action_renew_agreement()
        self.assertEqual(app.agreement_expiry, today + relativedelta(years=1))
        self.assertEqual(app.partner_id.sgc_broker_status, 'registered')
        self.assertEqual(app.partner_id.sgc_agreement_expiry, app.agreement_expiry)
        # renewing early extends from the current expiry, not from today
        before = app.agreement_expiry
        app.action_renew_agreement()
        self.assertEqual(app.agreement_expiry, before + relativedelta(years=1))

    def test_document_expiry_is_monitored_and_settings_are_respected(self):
        app = self._registered_app()
        today = fields.Date.today()
        doc = app.sudo().document_ids.filtered(lambda d: d.type_id.has_expiry)[:1]
        doc.expiry_date = today + timedelta(days=8)
        self.Application._cron_check_expiries()
        self.assertFalse(self._notices(app, 'Reminder: %s' % doc.type_id.name))
        self.env['ir.config_parameter'].set_param('sgc_broker.expiry_pre_days', '10')
        self.env['ir.config_parameter'].set_param('sgc_broker.extra_notify_emails', 'compliance@example.com')
        self.Application._cron_check_expiries()
        notices = self._notices(app, 'Reminder: %s' % doc.type_id.name)
        self.assertEqual(len(notices), 1)
        self.assertIn('compliance@example.com', notices.email_to)
        self.env['ir.config_parameter'].set_param('sgc_broker.agreement_validity_months', '24')
        app.action_renew_agreement()
        self.assertGreaterEqual(app.agreement_expiry, today + relativedelta(years=2))

    def test_not_registered_applications_are_not_monitored(self):
        app = self._verified_app()
        self._details(app)
        app.sudo().trade_license_expiry = fields.Date.today() - timedelta(days=3)
        self.Application._cron_check_expiries()
        self.assertFalse(app.sudo().expiry_tracker_ids)

    def test_agreement_report_renders(self):
        app = self._verified_app()
        report = self.env.ref('sgc_broker_registration.action_report_broker_agreement')
        html, _fmt = report._render_qweb_html(report.report_name, app.ids)
        self.assertIn(b'BROKERAGE COOPERATION AGREEMENT', html)
        self.assertIn(b'Acme Brokers LLC', html)
        res = self.url_open('/broker/application/%s/agreement' % app.access_token)
        self.assertEqual(res.status_code, 200)

    # -- hardening / abuse ------------------------------------------------
    def test_control_characters_and_oversized_input_are_refused_not_500(self):
        app = self._verified_app()
        for over, msg in (({'full_name': 'Bad\x00Name'}, 'invalid characters'),
                          ({'full_name': 'A' * 5000}, 'too long'),
                          ({'street': 'B' * 5000}, 'too long'),
                          ({'company_name': 'x\x07y'}, 'invalid characters')):
            res = self._post('/broker/application/%s/details' % app.access_token, over,
                             '/broker/application/%s' % app.access_token)
            self.assertEqual(res.status_code, 200, over)
            self.assertIn(msg, res.text)
        self.assertEqual(app.state, 'verified')

    def test_database_blocks_two_open_applications_for_one_email(self):
        base = {'applicant_type': 'company', 'emirate': 'dubai', 'company_name': 'X', 'full_name': 'Y',
                'email': 'dup@acme.test', 'phone': '+971501234567'}
        first = self.Application.create(base)
        with self.assertRaises(IntegrityError), mute_logger('odoo.sql_db'), self.cr.savepoint():
            self.Application.create(base)
        first.state = 'rejected'                      # after a rejection the applicant may re-apply
        first.flush_recordset()
        self.assertTrue(self.Application.create(base))

    def test_document_count_caps(self):
        from ..models import application_document as ad
        app = self._verified_app()
        trade = self.env.ref('sgc_broker_registration.doctype_trade_license')
        Doc = self.env['sgc.broker.application.document']
        vals = {'application_id': app.id, 'type_id': trade.id, 'filename': 'a.pdf', 'file': base64_pdf(),
                'expiry_date': fields.Date.today() + timedelta(days=100)}
        for _i in range(ad.MAX_DOCS_PER_TYPE):
            Doc.create(vals)
        with self.assertRaises(ValidationError):
            Doc.create(vals)

    def test_uploaded_filenames_are_reduced_to_a_safe_base_name(self):
        app = self._verified_app()
        trade = self.env.ref('sgc_broker_registration.doctype_goaml')
        Doc = self.env['sgc.broker.application.document']
        for raw, expected in (('../../etc/passwd.pdf', 'passwd.pdf'), ('C:\\evil\\scan.pdf', 'scan.pdf'),
                              ('a<b>"c|.pdf', 'abc.pdf'), ('ok name.PDF', 'ok name.PDF'),
                              (('x' * 400) + '.pdf', None)):
            doc = Doc.create({'application_id': app.id, 'type_id': trade.id, 'filename': raw, 'file': base64_pdf()})
            if expected:
                self.assertEqual(doc.filename, expected)
            else:
                self.assertLessEqual(len(doc.filename), 150)
                self.assertTrue(doc.filename.endswith('.pdf'), 'the extension survives shortening')
            doc.unlink()

    def test_output_is_escaped_on_portal_pages(self):
        app = self._verified_app()
        self._details(app, full_name='<script>alert(1)</script>', company_name='<img src=x onerror=alert(2)>')
        html = self.url_open('/broker/application/%s' % app.access_token).text
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertNotIn('<img src=x onerror=alert(2)>', html)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)

    def test_verify_serialises_through_row_lock_and_caps_guesses(self):
        self._register()
        app = self.Application.search([('email', '=', 'jane@acme.test')])
        wrong = '000000' if self._last_code(app.email) != '000000' else '111111'
        results = [app.verify_code(wrong) for _i in range(20)]
        self.assertEqual(results.count('bad') + results.count('locked'), 20)
        self.assertEqual(results.count('bad'), 4)
        self.assertEqual(app.sudo().code_attempts, 5)

    def test_expiry_cron_stops_when_out_of_time_and_resumes(self):
        apps = self.Application
        for n in range(3):
            apps |= self._registered_app_for('batch%d@acme.test' % n)
        for app in apps:
            app.sudo().trade_license_expiry = fields.Date.today() - timedelta(days=1)
        calls = []

        def out_of_time(cron, processed=0, *, remaining=None, deactivate=False):
            calls.append(processed)
            return float('inf') if remaining is not None else 0

        with patch.object(type(self.env['ir.cron']), '_commit_progress', out_of_time), \
                patch('odoo.addons.sgc_broker_registration.models.broker_application.CRON_COMMIT_EVERY', 1):
            self.Application.with_context(cron_id=1)._cron_check_expiries()
        done_first = apps.sudo().expiry_tracker_ids.filtered(
            lambda t: t.key == 'trade_license' and t.last_alert_date)
        self.assertEqual(len(done_first), 1)
        self.Application._cron_check_expiries()
        done_all = apps.sudo().expiry_tracker_ids.filtered(lambda t: t.key == 'trade_license' and t.last_alert_date)
        self.assertEqual(len(done_all), 3)

    def _registered_app_for(self, email):
        app = self._verified_app(email=email)
        self._details(app)
        self._upload_all_required(app)
        self._submit(app)
        app = app.with_user(self.officer)
        app.document_ids.action_accept()
        app.action_approve()
        return app

    def test_administrator_gets_manager_rights_on_install(self):
        admin = self.env.ref('base.user_admin')
        self.assertTrue(admin.has_group('sgc_broker_registration.group_broker_manager'))

    def test_per_ip_rate_limit_is_enforced_and_configurable(self):
        self.env['ir.config_parameter'].set_param('sgc_broker.max_registrations_per_ip_hour', '3')
        outcomes = []
        for n in range(5):
            res = self._post('/broker/register/submit',
                             {'applicant_type': 'company', 'emirate': 'dubai', 'company_name': 'C%d' % n,
                              'full_name': 'N', 'email': 'ip%d@acme.test' % n, 'phone': '+971501234567'},
                             '/broker/register')
            outcomes.append('accepted' if self.Application.search([('email', '=', 'ip%d@acme.test' % n)]) else 'blocked')
        self.assertEqual(outcomes, ['accepted'] * 3 + ['blocked'] * 2)
        self.assertIn('Too many registrations', res.text)
        self.env['ir.config_parameter'].set_param('sgc_broker.max_registrations_per_ip_hour', '100')
        self._post('/broker/register/submit',
                   {'applicant_type': 'company', 'emirate': 'dubai', 'company_name': 'Cx', 'full_name': 'N',
                    'email': 'ip9@acme.test', 'phone': '+971501234567'}, '/broker/register')
        self.assertTrue(self.Application.search([('email', '=', 'ip9@acme.test')]))
