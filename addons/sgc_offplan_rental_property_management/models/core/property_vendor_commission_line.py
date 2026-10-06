# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
from odoo import api, fields, models


class PropertyVendorCommissionLine(models.Model):
    _name = 'property.vendor.commission.line'
    _inherit = ['commission.line.mixin', 'sgc.critical.audit.mixin']
    _description = 'Booking Commission Distribution Line'

    vendor_id = fields.Many2one(
        'property.vendor',
        string='Booking',
        required=True,
        ondelete='cascade',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='vendor_id.currency_id',
        store=True,
    )
    computation_type = fields.Selection(
        selection_add=[('property_price', 'Sale Price')],
        ondelete={'property_price': 'set default'},
    )
    base_line_id = fields.Many2one(
        'property.vendor.commission.line',
        string='Base Commission Line',
        domain="[('vendor_id', '=', vendor_id), ('id', '!=', id)]",
        help='The other beneficiary line this percentage is calculated against, '
             'when Computation Type is "Commission Received".',
    )

    @api.depends('vendor_id.sale_price', 'computation_type',
                 'commission_percentage', 'commission_fixed_amount', 'base_line_id')
    def _compute_commission_amount(self):
        self._set_commission_amounts()

    def _get_contract_value_base(self):
        self.ensure_one()
        return self.vendor_id.sale_price or 0.0

    def _get_base_line(self):
        self.ensure_one()
        return self.base_line_id

    @api.constrains('computation_type', 'base_line_id')
    def _check_base_line(self):
        super()._check_base_line()

    def _get_parent_contract(self):
        self.ensure_one()
        return self.vendor_id
