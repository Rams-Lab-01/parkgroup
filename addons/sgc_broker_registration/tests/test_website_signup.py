import re

from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestBrokerWebsiteSignup(HttpCase):

    def _csrf(self, url):
        match = re.search(r'name="csrf_token"\s+value="([^"]+)"', self.url_open(url).text)
        self.assertTrue(match)
        return match.group(1)

    def test_landing_is_public_and_lists_documents(self):
        res = self.url_open('/brokers')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Become a Registered Broker', res.text)
        self.assertIn('/broker/register', res.text)
        self.assertIn('approves your application', res.text)

    def test_menu_entry_exists(self):
        menu = self.env.ref('sgc_broker_registration.menu_brokers')
        self.assertEqual(menu.url, '/brokers')
        self.assertIn('Brokers', self.url_open('/').text)

    def test_open_by_default_and_closable(self):
        self.assertEqual(self.url_open('/broker/register').status_code, 200)
        self.assertIn('Broker Registration', self.url_open('/broker/register').text)
        self.env['ir.config_parameter'].sudo().set_param('sgc_broker.open_signup', 'False')
        self.assertIn('Registrations are closed', self.url_open('/broker/register').text)
        self.assertIn('New registrations are currently closed', self.url_open('/brokers').text)
        token = self._csrf('/broker/resume')
        res = self.url_open('/broker/register/submit', data={
            'csrf_token': token, 'applicant_type': 'individual', 'emirate': 'dubai',
            'full_name': 'Closed Test', 'email': 'closed@example.com', 'phone': '+971501234567'})
        self.assertIn('Registrations are closed', res.text)
        self.assertFalse(self.env['sgc.broker.application'].sudo().search([('email', '=', 'closed@example.com')]))

    def test_resume_never_reveals_whether_an_application_exists(self):
        app = self.env['sgc.broker.application'].sudo().create({
            'applicant_type': 'individual', 'emirate': 'dubai', 'full_name': 'Resume Test',
            'email': 'resume@example.com', 'phone': '+971501234567'})
        token = self._csrf('/broker/resume')
        known = self.url_open('/broker/resume', data={'csrf_token': token, 'email': 'resume@example.com'})
        unknown = self.url_open('/broker/resume', data={'csrf_token': token, 'email': 'nobody@example.com'})
        self.assertIn('If an application exists', known.text)
        self.assertIn('If an application exists', unknown.text)
        self.assertNotIn(app.access_token, known.text)
        self.assertTrue(app.resume_last_sent or app.code_last_sent)
        self.assertFalse(self.env['sgc.broker.application'].sudo().search([('email', '=', 'nobody@example.com')]))
        self.assertNotEqual(app.state, 'approved', 'nothing is approved by signing up')
