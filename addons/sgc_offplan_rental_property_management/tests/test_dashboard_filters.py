from datetime import date

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install', 'dash_filters')
class TestDashboardFiltersAndRankings(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Prop = cls.env['property.details']
        cls.p1 = cls.env['property.project'].create({'name': 'Dash Tower A'})
        cls.p2 = cls.env['property.project'].create({'name': 'Dash Tower B'})
        cls.vendor = cls.env['res.partner'].create({'name': 'Dash Vendor'})
        cls.brokers = [cls.env['res.partner'].create({'name': 'Broker %02d' % i, 'user_type': 'broker'})
                       for i in range(12)]
        cls.sales = [cls.env['res.users'].create({'name': 'Sales %02d' % i, 'login': 'dash_s%02d' % i})
                     for i in range(3)]

    def _booking(self, project, broker, sales, price, when, cancelled=False):
        unit = self.Prop.create({'name': 'Dash unit', 'project_id': project.id, 'sale_price': price})
        booking = self.env['property.vendor'].create({
            'vendor_id': self.vendor.id, 'property_id': unit.id, 'broker_id': broker.id if broker else False,
            'salesperson_id': sales.id if sales else False, 'sale_price': price, 'contract_date': when})
        if cancelled:
            booking.state = 'cancelled'
        return booking

    def test_rankings_top10_sorted_and_cancelled_excluded(self):
        for i, broker in enumerate(self.brokers):                  # 12 brokers, value grows with i
            self._booking(self.p1, broker, self.sales[i % 3], 1000 * (i + 1), date(2026, 3, 1))
        self._booking(self.p1, self.brokers[0], self.sales[0], 9_999_999, date(2026, 3, 1), cancelled=True)
        res = self.Prop.get_sales_rankings({'project_ids': [self.p1.id]})
        names = [r['name'] for r in res['brokers']]
        self.assertEqual(len(names), 10)
        self.assertEqual(names[0], 'Broker 11')
        self.assertEqual([r['rank'] for r in res['brokers']], list(range(1, 11)))
        self.assertNotIn('Broker 00', names, 'the cancelled 9.99M booking must not lift anyone into the top 10')
        values = [r['value'] for r in res['brokers']]
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(len(res['salespeople']), 3)

    def test_date_and_project_filters(self):
        self._booking(self.p1, self.brokers[0], self.sales[0], 100, date(2026, 1, 10))
        self._booking(self.p2, self.brokers[0], self.sales[0], 200, date(2026, 6, 10))
        both = self.Prop.get_sales_rankings({'project_ids': [self.p1.id, self.p2.id]})
        self.assertEqual(both['brokers'][0]['value'], 300)
        jan = self.Prop.get_sales_rankings({'project_ids': [self.p1.id, self.p2.id],
                                            'date_from': '2026-01-01', 'date_to': '2026-02-01'})
        self.assertEqual(jan['brokers'][0]['value'], 100)
        only_b = self.Prop.get_sales_rankings({'project_ids': [self.p2.id]})
        self.assertEqual(only_b['brokers'][0]['value'], 200)
        swapped = self.Prop.get_sales_rankings({'project_ids': [self.p1.id, self.p2.id],
                                                'date_from': '2026-02-01', 'date_to': '2026-01-01'})
        self.assertEqual(swapped['brokers'][0]['value'], 100, 'a reversed range is normalised, not an error')

    def test_person_filters_and_default_salesperson(self):
        self._booking(self.p1, self.brokers[1], self.sales[1], 500, date(2026, 2, 2))
        self._booking(self.p1, self.brokers[2], self.sales[2], 700, date(2026, 2, 2))
        res = self.Prop.get_sales_rankings({'project_ids': [self.p1.id], 'broker_id': self.brokers[2].id})
        self.assertEqual([r['name'] for r in res['brokers']], ['Broker 02'])
        res = self.Prop.get_sales_rankings({'project_ids': [self.p1.id], 'salesperson_id': self.sales[1].id})
        self.assertEqual([r['name'] for r in res['salespeople']], ['Sales 01'])
        booking = self.env['property.vendor'].create({'vendor_id': self.vendor.id})
        self.assertEqual(booking.salesperson_id, self.env.user, 'creator is credited by default')

    def test_garbage_filters_are_ignored_safely(self):
        for bad in (None, 'x', [], {'project_ids': ['1; drop table', None], 'broker_id': 'abc',
                                    'date_from': 'not a date', 'salesperson_id': {}}):
            self.assertIsInstance(self.Prop.get_sales_rankings(bad), dict)
            self.assertIn('total_units', self.Prop.get_development_kpis(bad))

    def test_kpis_follow_the_project_filter(self):
        self.Prop.create({'name': 'A1', 'project_id': self.p1.id})
        self.Prop.create({'name': 'A2', 'project_id': self.p1.id})
        self.Prop.create({'name': 'B1', 'project_id': self.p2.id})
        a = self.Prop.get_development_kpis({'project_ids': [self.p1.id]})
        b = self.Prop.get_development_kpis({'project_ids': [self.p2.id]})
        self.assertEqual((a['total_units'], b['total_units']), (2, 1))
        self.assertGreaterEqual(self.Prop.get_development_kpis()['total_units'], 3)

    def test_filter_options(self):
        self._booking(self.p1, self.brokers[3], self.sales[0], 10, date(2026, 1, 1))
        opts = self.Prop.get_dashboard_filter_options()
        self.assertIn('Dash Tower A', [p['name'] for p in opts['projects']])
        self.assertIn('Broker 03', [b['name'] for b in opts['brokers']])
        self.assertIn('Sales 00', [u['name'] for u in opts['salespeople']])
