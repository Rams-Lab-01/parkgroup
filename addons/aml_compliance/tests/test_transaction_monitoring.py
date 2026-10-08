from odoo.tests.common import TransactionCase
from datetime import timedelta
from odoo import fields


class TestTransactionAlert(TransactionCase):
    def setUp(self):
        super().setUp()
        self.partner = self.env['res.partner'].create({
            'name': 'Alert Test Customer',
        })
        self.rule = self.env['aml.monitoring.rule'].create({
            'name': 'Test Threshold Rule',
            'code': 'TEST_THRESHOLD',
            'rule_type': 'threshold',
            'threshold_amount': 10000.0,
            'severity': 'medium',
        })

    def test_create_alert_on_threshold(self):
        """Alert created when amount exceeds threshold."""
        yesterday = fields.Datetime.now() - timedelta(days=1)
        income_account = self.env['account.account'].create({
            'name': 'Wave4 Test Income Account',
            'code': 'W4INC',
            'account_type': 'income',
            'company_ids': [(6, 0, [self.env.company.id])],
        })
        # No chart-of-accounts localization is installed, so the partner
        # has no receivable account either -- Odoo auto-creates the
        # invoice's balancing payment-term line from it and would
        # otherwise fail the same accountable-line check with a NULL
        # account_id.
        receivable_account = self.env['account.account'].create({
            'name': 'Wave4 Test Receivable Account',
            'code': 'W4REC',
            'account_type': 'asset_receivable',
            'reconcile': True,
            'company_ids': [(6, 0, [self.env.company.id])],
        })
        self.partner.property_account_receivable_id = receivable_account.id
        # A bare install has no chart-of-accounts localization, so no
        # sale journal exists yet either -- create one rather than
        # depend on demo/localization data being present.
        sale_journal = self.env['account.journal'].search(
            [('type', '=', 'sale'), ('company_id', '=', self.env.company.id)],
            limit=1,
        )
        if not sale_journal:
            sale_journal = self.env['account.journal'].create({
                'name': 'Wave4 Test Sales Journal',
                'type': 'sale',
                'code': 'W4SJ',
                'company_id': self.env.company.id,
            })
        invoice = self.env['account.move'].create({
            'partner_id': self.partner.id,
            'move_type': 'out_invoice',
            'journal_id': sale_journal.id,
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': [(0, 0, {
                'name': 'Test line',
                'quantity': 1,
                'price_unit': 15000.0,
                'account_id': income_account.id,
            })],
        })
        invoice.action_post()
        alert = self.env['aml.transaction.alert'].create({
            'rule_id': self.rule.id,
            'partner_id': self.partner.id,
            'transaction_amount': 15000.0,
            'invoice_id': invoice.id,
            'transaction_date': fields.Date.today(),
            'alert_description': 'Test threshold alert',
        })
        self.assertEqual(alert.state, 'new')
        self.assertEqual(alert.severity, 'medium')
        self.assertEqual(alert.transaction_amount, 15000.0)

    def test_alert_state_workflow(self):
        """Alert moves through investigation workflow correctly."""
        alert = self.env['aml.transaction.alert'].create({
            'rule_id': self.rule.id,
            'partner_id': self.partner.id,
            'transaction_amount': 20000.0,
        })
        self.assertEqual(alert.state, 'new')

        alert.action_investigate()
        self.assertEqual(alert.state, 'investigating')

        alert.action_escalate()
        self.assertEqual(alert.state, 'escalated')

    def test_false_positive_requires_notes(self):
        """Marking false positive requires investigation notes."""
        alert = self.env['aml.transaction.alert'].create({
            'rule_id': self.rule.id,
            'partner_id': self.partner.id,
            'transaction_amount': 20000.0,
        })
        alert.action_investigate()
        alert.write({'investigation_notes': 'Reviewed: false alarm'})
        alert.action_false_positive()
        self.assertEqual(alert.state, 'false_positive')
