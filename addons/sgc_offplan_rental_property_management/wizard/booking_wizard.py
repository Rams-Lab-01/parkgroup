from odoo import fields, api, models, _


class BookingWizard(models.TransientModel):
    _name = 'booking.wizard'
    _description = 'Create Booking While Property on Sale'

    # Project-level booking support
    from_project = fields.Boolean(
        string='From Project',
        default=False,
        help='Booking created from a project context')
    project_id = fields.Many2one(
        'property.project',
        string='Project',
        help='Project from which this booking was initiated')

    customer_id = fields.Many2one('res.partner', string='Customer', domain="[('user_type','=','customer')]")
    property_id = fields.Many2one('property.details', string='Property')
    price = fields.Monetary(related="property_id.price")
    registration_fee = fields.Monetary(related="property_id.registration_fee", string="Registration Fee")
    admin_fee = fields.Monetary(related="property_id.admin_fee", string="Admin Fee")
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency')

    payment_plan = fields.Selection([
        ('offplan', 'Offplan'),
        ('sale', 'Sale'),
        ('rent', 'Rent'),
    ], string='Payment Plan', default='sale', required=True)

    book_price = fields.Monetary(string="Advance")
    ask_price = fields.Monetary(string="Customer Price")
    sale_price = fields.Monetary(related="property_id.sale_price", string="Sale Price")
    is_any_broker = fields.Boolean(string='Any Broker?')
    broker_id = fields.Many2one('res.partner', string='Broker', domain=[('user_type', '=', 'broker')])
    commission_type = fields.Selection([('f', 'Fix'), ('p', 'Percentage')], string="Commission Type")
    broker_commission = fields.Monetary(string='Commission')
    broker_commission_percentage = fields.Float(string='Percentage')
    commission_from = fields.Selection([('customer', 'Customer'),
                                        ('landlord', 'Landlord',)],
                                       default='customer', string="Commission From")
    from_inquiry = fields.Boolean('From Enquiry')
    note = fields.Text(string="Note", translate=True)
    lead_id = fields.Many2one('crm.lead', string="Enquiry", domain="[('property_id','=',property_id)]")

    # Maintenance and utility Service
    is_any_maintenance = fields.Boolean(related="property_id.is_maintenance_service")
    total_maintenance = fields.Monetary(related="property_id.total_maintenance")
    is_utility_service = fields.Boolean(related="property_id.is_extra_service")
    total_service = fields.Monetary(related="property_id.extra_service_cost")

    # Booking Item
    booking_item_id = fields.Many2one('product.product', string="Booking Item")
    broker_item_id = fields.Many2one('product.product', string="Broker Item")

    # Deprecated
    inquiry_id = fields.Many2one('sale.inquiry', string="Enquiry ")

    @api.model
    def default_get(self, fields):
        res = super(BookingWizard, self).default_get(fields)
        active_id = self._context.get('active_id')
        project_id_from_ctx = self._context.get('default_project_id')

        # Check if active_id points to a valid property.details record
        property_id_rec = self.env['property.details'].browse(active_id) if active_id else self.env['property.details']
        is_property_context = bool(property_id_rec.exists())

        # Scenario 1: Coming from a project context (default_project_id set and no valid property)
        if project_id_from_ctx and not is_property_context:
            res['from_project'] = True
            res['project_id'] = project_id_from_ctx
            default_broker_item = self.env['ir.config_parameter'].sudo().get_param(
                'sgc_offplan_rental_property_management.account_broker_item_id')
            default_deposit_item = self.env['ir.config_parameter'].sudo().get_param(
                'sgc_offplan_rental_property_management.account_deposit_item_id')
            res['booking_item_id'] = int(default_deposit_item) if default_deposit_item else self.env.ref(
                'sgc_offplan_rental_property_management.property_product_2').id
            res['broker_item_id'] = int(default_broker_item) if default_broker_item else self.env.ref(
                'sgc_offplan_rental_property_management.property_product_3').id
            return res

        # Scenario 2: Coming from a property.details record (existing behavior)
        default_broker_item = self.env['ir.config_parameter'].sudo().get_param(
            'sgc_offplan_rental_property_management.account_broker_item_id')
        default_deposit_item = self.env['ir.config_parameter'].sudo().get_param(
            'sgc_offplan_rental_property_management.account_deposit_item_id')
        res['property_id'] = property_id_rec.id
        if property_id_rec.sale_lease == 'sale':
            res['ask_price'] = property_id_rec.total_customer_obligation or property_id_rec.price
        else:
            res['ask_price'] = property_id_rec.price
        # Auto-suggest the booking advance from the property's own booking
        # rate, same "auto-suggest, stays editable" treatment as the
        # Pricing & Fees tab -- book_price remains a plain, overridable
        # field; this only pre-fills it when the property defines a
        # percentage-based booking rate.
        if property_id_rec.booking_type == 'percentage' and property_id_rec.booking_percentage:
            res['book_price'] = property_id_rec.price * property_id_rec.booking_percentage / 100.0
        res['booking_item_id'] = int(default_deposit_item) if default_deposit_item else self.env.ref(
            'sgc_offplan_rental_property_management.property_product_2').id
        res['broker_item_id'] = int(default_broker_item) if default_broker_item else self.env.ref(
            'sgc_offplan_rental_property_management.property_product_3').id
        return res

    def create_booking_action(self):
        self.customer_id.user_type = "customer"

        commission_type_map = {'f': 'fixed', 'p': 'percentage'}
        seq = self.env['ir.sequence'].next_by_code('property.vendor') or _('New')

        # property.vendor only tracks the booking itself (parties, price, broker
        # commission); registration/admin fee inheritance, payment-plan generation and
        # invoicing are not modelled on it and are handled separately.
        data = {
            'name': seq,
            'sold_seq': seq,
            'customer_id': self.customer_id.id,
            'vendor_id': self.property_id.owner_id.id,
            'property_id': self.property_id.id,
            'sale_price': self.ask_price,
            'broker_id': self.broker_id.id,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'contract_date': fields.Date.context_today(self),
            'state': 'draft',
        }
        if self.commission_type and self.broker_id:
            data['commission_line_ids'] = [(0, 0, {
                'partner_id': self.broker_id.id,
                'category': 'external',
                'role': 'broker',
                'commission_type': commission_type_map.get(self.commission_type, 'percentage'),
                'commission_percentage': self.broker_commission_percentage,
                'commission_fixed_amount': self.broker_commission,
            })]

        booking_id = self.env['property.vendor'].create(data)
        self.property_id.sold_booking_id = booking_id.id

        # Send booking confirmation email
        mail_template = self.env.ref(
            'sgc_offplan_rental_property_management.property_book_mail_template')
        if mail_template:
            mail_template.send_mail(booking_id.id, force_send=True)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Property Booking',
            'res_model': 'property.vendor',
            'res_id': booking_id.id,
            'view_mode': 'form,list',
            'target': 'current'
        }

    @api.onchange('project_id')
    def _onchange_project_id(self):
        for rec in self:
            if rec.project_id:
                return {'domain': {'property_id': [('project_id', '=', rec.project_id.id)]}}
            return {'domain': {'property_id': []}}

    @api.onchange('from_inquiry')
    def _onchange_property_sale_inquiry(self):
        inquiry_ids = self.env['sale.inquiry'].search(
            [('property_id', '=', self.property_id.id)]).mapped('id')
        for rec in self:
            if not rec.from_inquiry:
                return
            return {'domain': {'inquiry_id': [('id', 'in', inquiry_ids)]}}

    @api.onchange('lead_id')
    def _onchange_ask_price(self):
        for rec in self:
            if not rec.from_inquiry and not rec.lead_id:
                return
            rec.ask_price = rec.lead_id.ask_price
            rec.note = rec.lead_id.description
            rec.customer_id = rec.lead_id.partner_id.id
