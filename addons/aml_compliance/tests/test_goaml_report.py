from odoo.tests import tagged
from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


@tagged('post_install', '-at_install', 'aml_compliance')
class TestGoAMLReportValidation(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env.user.write({
            'group_ids': [(4, self.env.ref('aml_compliance.group_aml_officer').id)],
        })
        self.partner = self.env['res.partner'].create({
            'name': 'KYC Test Customer',
            'email': 'kyc.test@example.com',
            'vat': 'UAE-123456',
        })

    def _create_report(self, report_type, **kwargs):
        vals = {
            'report_type': report_type,
            'partner_id': self.partner.id,
            'reason_for_suspicion': 'Test reason',
        }
        vals.update(kwargs)
        return self.env['aml.goaml.report'].create(vals)

    def test_ctr_requires_threshold_and_cash_type(self):
        report = self._create_report(
            'ctr',
            transaction_amount=50000,
            transaction_type='cash',
            transaction_date='2026-03-01',
        )
        with self.assertRaises(ValidationError):
            report.action_submit_to_mlro()

    def test_sar_disallows_transaction_amount(self):
        report = self._create_report('sar', transaction_amount=1000)
        with self.assertRaises(ValidationError):
            report.action_submit_to_mlro()

    def test_str_requires_transaction_fields(self):
        report = self._create_report('str')
        with self.assertRaises(ValidationError):
            report.action_submit_to_mlro()

    def test_valid_ctr_can_submit(self):
        report = self._create_report(
            'ctr',
            transaction_amount=55000,
            transaction_type='cash',
            transaction_date='2026-03-01',
        )
        report.action_submit_to_mlro()
        self.assertEqual(report.state, 'submitted')
