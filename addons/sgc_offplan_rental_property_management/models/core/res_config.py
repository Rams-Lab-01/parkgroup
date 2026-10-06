# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import models, fields, api


class RentalConfig(models.TransientModel):
    _inherit = 'res.config.settings'

    reminder_days = fields.Integer(string='Days', default=5,
                                   config_parameter='sgc_offplan_rental_property_management.reminder_days', readonly=False)
    sale_reminder_days = fields.Integer(string="Days ", default=3,
                                        config_parameter='sgc_offplan_rental_property_management.sale_reminder_days', readonly=False)
    invoice_post_type = fields.Selection([('manual', 'Invoice Post Manually'),
                                          ('automatically', 'Invoice Post Automatically')], string="Invoice Post",
                                         default='manual', config_parameter='sgc_offplan_rental_property_management.invoice_post_type', readonly=False)

    month_days = fields.Integer(string="Month Days",
                                default=30, config_parameter='sgc_offplan_rental_property_management.month_days', readonly=False)
    quarter_days = fields.Integer(string="Quarter Days",
                                  default=90, config_parameter='sgc_offplan_rental_property_management.quarter_days', readonly=False)
    year_days = fields.Integer(string="Year Days",
                               default=365, config_parameter='sgc_offplan_rental_property_management.year_days', readonly=False)

    # Default Account Product
    installment_item_id = fields.Many2one('product.product', string="Installment Item",
                                          default=lambda self: self.env.ref('sgc_offplan_rental_property_management.property_product_1',
                                                                            raise_if_not_found=False),
                                          config_parameter='sgc_offplan_rental_property_management.account_installment_item_id', readonly=False)
    deposit_item_id = fields.Many2one('product.product', string="Deposit Item",
                                      default=lambda self: self.env.ref('sgc_offplan_rental_property_management.property_product_2',
                                                                        raise_if_not_found=False),
                                      config_parameter='sgc_offplan_rental_property_management.account_deposit_item_id', readonly=False)
    broker_item_id = fields.Many2one('product.product', string="Broker Commission Item",
                                     default=lambda self: self.env.ref('sgc_offplan_rental_property_management.property_product_3',
                                                                       raise_if_not_found=False),
                                     config_parameter='sgc_offplan_rental_property_management.account_broker_item_id', readonly=False)
    maintenance_item_id = fields.Many2one('product.product', string="Maintenance Item",
                                          default=lambda self: self.env.ref('sgc_offplan_rental_property_management.property_product_4',
                                                                            raise_if_not_found=False),
                                          config_parameter='sgc_offplan_rental_property_management.account_maintenance_item_id', readonly=False)

    # Fee Configuration
    registration_fee_type = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percentage', 'Percentage of Sale Price')
    ], string='Registration Fee Type', default='percentage',
       config_parameter='sgc_offplan_rental_property_management.default_registration_fee_type',
       readonly=False,
       help="Method used to calculate the property registration fee charged by the "
            "emirate's land registration authority (e.g. Dubai Land Department).")

    registration_fee_percentage = fields.Float(
        string='Registration Fee Percentage',
        default=4.0,
        config_parameter='sgc_offplan_rental_property_management.default_registration_fee_percentage',
        readonly=False,
        help='Registration fee as percentage of sale price (e.g., 4.0 for Dubai; '
             'other emirates set their own rate)')

    registration_fee_amount = fields.Float(
        string='Registration Fee (Fixed)',
        default=0.0,
        config_parameter='sgc_offplan_rental_property_management.default_registration_fee_amount',
        readonly=False,
        help='Fixed registration fee amount')

    admin_fee_type = fields.Selection([
        ('fixed', 'Fixed Amount'),
        ('percentage', 'Percentage of Sale Price')
    ], string='Admin Fee Type', default='percentage',
       config_parameter='sgc_offplan_rental_property_management.default_admin_fee_type',
       readonly=False,
       help='Administrative fee calculation method')

    admin_fee_percentage = fields.Float(
        string='Admin Fee Percentage',
        default=2.0,
        config_parameter='sgc_offplan_rental_property_management.default_admin_fee_percentage',
        readonly=False,
        help='Admin Fee as percentage of sale price (e.g., 2.0 for 2%)')

    admin_fee_amount = fields.Float(
        string='Admin Fee (Fixed)',
        default=0.0,
        config_parameter='sgc_offplan_rental_property_management.default_admin_fee_amount',
        readonly=False,
        help='Fixed Admin Fee amount')

    # Commission Eligibility
    commission_eligibility_sale_pct = fields.Float(
        string='Sale Commission Eligibility %',
        default=20.0,
        config_parameter='sgc_offplan_rental_property_management.commission_eligibility_sale_pct',
        readonly=False,
        help='For payment-plan sales, the minimum percentage of the sale price that must '
             'be paid before commission bills can be generated.')

    # File Upload Security
    max_file_upload_size = fields.Integer(
        string='Max File Upload Size (MB)',
        default=10,
        config_parameter='sgc_offplan_rental_property_management.max_file_upload_size',
        readonly=False,
        help='Maximum allowed file size for document uploads in megabytes. Default: 10 MB')
    # Sales Consolidation
    confirm_sales_requires_payment = fields.Boolean(
        string='Require Payment Before Confirming Sale',
        default=True,
        config_parameter='sgc_mt.confirm_sales_requires_payment',
        readonly=False,
        help='If True (hard gate), payment must be recorded before a sale can be confirmed from a booking. '
             'If False (permissive), users can confirm sale without payment but must provide an acknowledgement.')
