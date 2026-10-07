from odoo.tests.common import TransactionCase


class EoiCommon(TransactionCase):
    """Real accounting: the UAE chart is loaded and payments are really posted - nothing is faked."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        if not cls.company.chart_template:
            cls.env['account.chart.template'].try_loading('ae', cls.company, install_demo=False)
        cls.env['ir.config_parameter'].sudo().set_param('sgc_mt.confirm_sales_requires_payment', 'True')
        cls.journal = cls.env['account.journal'].search(
            [('type', '=', 'bank'), ('company_id', '=', cls.company.id)], limit=1)
        cls.project = cls.env['property.project'].create({'name': 'EOI Tower', 'company_id': cls.company.id})
        cls.customer = cls.env['res.partner'].create({'name': 'Layla Al Mansoori', 'email': 'layla@example.com'})
        cls.unit_seq = 0
        grp = 'sgc_offplan_rental_property_management.'
        users = cls.env['res.users'].with_context(no_reset_password=True)
        cls.manager = users.create({'name': 'EOI Manager', 'login': 'eoi_mgr',
                                    'group_ids': [(6, 0, [cls.env.ref('base.group_user').id,
                                                          cls.env.ref(grp + 'property_rental_manager').id])]})
        cls.officer = users.create({'name': 'EOI Officer', 'login': 'eoi_off',
                                    'group_ids': [(6, 0, [cls.env.ref('base.group_user').id,
                                                          cls.env.ref(grp + 'property_rental_officer').id])]})

    def new_unit(self, **kw):
        type(self).unit_seq += 1
        vals = {'name': 'Unit %s' % self.unit_seq, 'unit_number': str(100 + self.unit_seq),
                'project_id': self.project.id, 'company_id': self.company.id,
                'sale_price': 1500000.0, 'price': 1500000.0, 'booking_percentage': 10.0}
        vals.update(kw)
        return self.env['property.details'].create(vals)

    def new_eoi(self, unit=None, **kw):
        unit = unit or self.new_unit()
        vals = {'property_id': unit.id, 'partner_id': self.customer.id, 'amount': 50000.0}
        vals.update(kw)
        return self.env['property.eoi'].create(vals)

    def pay(self, record, amount, wizard_model=None):
        """Record a real posted payment through the same wizards the UI uses."""
        if record._name == 'property.eoi':
            wiz = self.env['property.eoi.payment.wizard'].create({
                'eoi_id': record.id, 'amount': amount, 'journal_id': self.journal.id, 'payment_mode': 'bank_transfer'})
        else:
            wiz = self.env['sale.record.payment.wizard'].create({
                'booking_id': record.id, 'payment_amount': amount, 'journal_id': self.journal.id})
        wiz.action_record()
        return record
