from datetime import timedelta
from unittest.mock import patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPdcCheque(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({'name': 'PDC Tenant'})
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', cls.env.company.id)], limit=1)
        cls.today = fields.Date.context_today(cls.env['sgc.pdc.cheque'])

    def _cheque(self, days=0, **kw):
        vals = {
            'partner_id': self.partner.id,
            'cheque_number': 'CHQ%s' % self.env['sgc.pdc.cheque'].search_count([]),
            'bank_name': 'Test Bank',
            'cheque_date': self.today + timedelta(days=days),
            'amount': 1000.0,
            'journal_id': self.journal.id,
        }
        vals.update(kw)
        return self.env['sgc.pdc.cheque'].create(vals)

    def test_workflow_and_payment(self):
        chq = self._cheque()
        self.assertNotEqual(chq.name, 'New')
        chq.action_register()
        chq.action_deposit()
        self.assertEqual(chq.state, 'deposited')
        chq.action_clear()
        self.assertEqual(chq.state, 'cleared')
        self.assertTrue(chq.payment_id)
        self.assertEqual(chq.payment_id.amount, 1000.0)

    def test_clear_registers_payment_on_invoice(self):
        inv = self.env['account.move'].create({
            'move_type': 'out_invoice', 'partner_id': self.partner.id,
            'invoice_date': self.today,
            'invoice_line_ids': [(0, 0, {'name': 'Rent', 'quantity': 1, 'price_unit': 1000.0})],
        })
        inv.action_post()
        chq = self._cheque(invoice_id=inv.id)
        chq.action_register()
        chq.action_clear()
        self.assertIn(inv.payment_state, ('paid', 'in_payment'))

    def test_bounce_requires_reason_flow(self):
        chq = self._cheque()
        chq.action_register()
        chq._do_bounce('Insufficient funds')
        self.assertEqual(chq.state, 'bounced')
        self.assertTrue(chq.activity_ids)

    def test_invalid_transitions(self):
        chq = self._cheque()
        with self.assertRaises(UserError):
            chq.action_deposit()

    def test_cron_notifies_once(self):
        up = self._cheque(days=3)
        mat = self._cheque(days=-1)
        far = self._cheque(days=60)
        (up | mat | far).action_register()
        self.env['sgc.pdc.cheque']._cron_notify_cheques()
        self.assertTrue(up.upcoming_notified)
        self.assertTrue(mat.matured_notified)
        self.assertFalse(far.upcoming_notified or far.matured_notified)
        self.assertTrue(up.activity_ids and mat.activity_ids)
        n = len(up.activity_ids)
        self.env['sgc.pdc.cheque']._cron_notify_cheques()
        self.assertEqual(len(up.activity_ids), n)

    def test_date_change_rearms_notification(self):
        chq = self._cheque(days=3)
        chq.action_register()
        self.env['sgc.pdc.cheque']._cron_notify_cheques()
        self.assertTrue(chq.upcoming_notified)
        chq.cheque_date = self.today + timedelta(days=5)
        self.assertFalse(chq.upcoming_notified)

    def test_delete_only_draft(self):
        chq = self._cheque()
        chq.action_register()
        with self.assertRaises(UserError):
            chq.unlink()

    def test_stage_dates_recorded(self):
        chq = self._cheque()
        self.assertTrue(chq.received_date)
        chq.action_register()
        chq.action_deposit()
        self.assertEqual(chq.deposit_date, self.today)
        chq._do_bounce('No funds')
        self.assertEqual(chq.bounce_date, self.today)
        chq.action_reset_draft()
        self.assertFalse(chq.bounce_date or chq.deposit_date)
        chq.action_register()
        chq.action_clear()
        self.assertEqual(chq.clear_date, self.today)

    def test_receipt_renders_for_both_directions(self):
        report = self.env.ref('sgc_pdc_management.action_report_pdc_receipt')
        for direction in ('inbound', 'outbound'):
            chq = self._cheque(direction=direction)
            html, _fmt = report._render_qweb_html(report.report_name, chq.ids)
            self.assertIn(b'CHEQUE RECEIPT' if direction == 'inbound' else b'PAYMENT VOUCHER', html)

    def test_maturity_status_is_searchable(self):
        up = self._cheque(days=3)
        mat = self._cheque(days=-2)
        draft = self._cheque(days=-2)
        (up | mat).action_register()
        cheques = up | mat | draft
        Cheque = self.env['sgc.pdc.cheque']
        self.assertEqual(Cheque.search([('id', 'in', cheques.ids), ('maturity_status', '=', 'matured')]), mat)
        self.assertEqual(Cheque.search([('id', 'in', cheques.ids), ('maturity_status', '=', 'upcoming')]), up)
        self.assertEqual(Cheque.search([('id', 'in', cheques.ids), ('maturity_status', '=', 'na')]), draft)
        self.assertEqual(
            Cheque.search([('id', 'in', cheques.ids), ('maturity_status', '!=', 'na')]), up | mat)

    def test_back_dated_cheque_is_allowed(self):
        chq = self._cheque(days=-5)
        self.assertEqual(chq.maturity_status, 'na')
        chq.action_register()
        self.assertEqual(chq.maturity_status, 'matured')

    def test_all_views_load_and_integrations_exist(self):
        views = self.env['sgc.pdc.cheque'].get_views(
            [(False, 'list'), (False, 'form'), (False, 'search'), (False, 'calendar'), (False, 'pivot')])
        self.assertEqual(set(views['views']), {'list', 'form', 'search', 'calendar', 'pivot'})
        for model in ('sale.contract', 'tenancy.details', 'rent.invoice'):
            self.assertIn('pdc_count', self.env[model]._fields)
            self.env[model].get_views([(False, 'form')])

    def test_pdc_user_can_work_without_admin_rights(self):
        user = self.env['res.users'].create({
            'name': 'PDC Clerk', 'login': 'pdc_clerk', 'email': 'clerk@example.com',
            'group_ids': [(6, 0, [self.env.ref('sgc_pdc_management.group_pdc_user').id])],
        })
        chq = self._cheque().with_user(user)
        chq.action_register()
        self.assertEqual(chq.state, 'registered')
        with self.assertRaises(Exception):
            chq.unlink()   # users cannot delete

    def test_navigation_links_from_contract_objects(self):
        contract = self.env['sale.contract'].create({'name': 'SC-1', 'buyer_id': self.partner.id})
        inst = self.env['sale.contract.installment'].create({
            'contract_id': contract.id, 'name': 'Inst 1',
            'due_date': self.today + timedelta(days=10), 'amount': 2500})
        chq = self._cheque(installment_id=inst.id, amount=2500)
        self.assertEqual(chq.sale_contract_id, contract)
        self.assertEqual(inst.pdc_count, 1)
        self.assertEqual(contract.pdc_count, 1)
        self.assertEqual(inst.action_view_pdc()['domain'], [('installment_id', '=', inst.id)])

    def test_cron_stops_when_out_of_time_and_resumes(self):
        cheques = self.env['sgc.pdc.cheque']
        for i in range(4):
            cheques |= self._cheque(days=-1 - i)
        cheques.action_register()
        calls = []

        def out_of_time(cron, processed=0, *, remaining=None, deactivate=False):
            calls.append(processed)
            return float('inf') if remaining is not None else 0          # budget gone after 1st record

        with patch.object(type(self.env['ir.cron']), '_commit_progress', out_of_time), \
                patch('odoo.addons.sgc_pdc_management.models.pdc_cheque.CRON_COMMIT_EVERY', 1):
            self.env['sgc.pdc.cheque'].with_context(cron_id=1)._cron_notify_cheques()
        self.assertEqual(len(cheques.filtered('matured_notified')), 1, 'stopped after the first record')
        self.env['sgc.pdc.cheque']._cron_notify_cheques()                # next scheduler run finishes the rest
        self.assertEqual(len(cheques.filtered('matured_notified')), 4)
        self.assertEqual(len(cheques.activity_ids), 4, 'no duplicates after resuming')

    def test_matured_alerts_come_first_in_a_backlog(self):
        up = self._cheque(days=2)
        mat = self._cheque(days=-3)
        (up | mat).action_register()
        order = []
        original = type(up)._notify_one

        def spy(rec, *a, **k):
            order.append(rec.id)
            return original(rec, *a, **k)

        with patch.object(type(up), '_notify_one', spy):
            self.env['sgc.pdc.cheque']._cron_notify_cheques()
        self.assertEqual(order, [mat.id, up.id])

    def test_administrator_gets_manager_rights_on_install(self):
        admin = self.env.ref('base.user_admin')
        self.assertTrue(admin.has_group('sgc_pdc_management.group_pdc_manager'))
