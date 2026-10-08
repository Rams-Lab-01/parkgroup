# -*- coding: utf-8 -*-

from odoo import models, fields, api

class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'sgc.critical.audit.mixin']

    tenancy_id = fields.Many2one(
        'tenancy.details',
        string='Tenancy',
        readonly=True,
        help='Related tenancy contract'
    )
    
    tenancy_property_id = fields.Many2one(
        'property.details',
        string='Tenancy Property',
        related='tenancy_id.property_id',
        store=True,
        readonly=True
    )
    
    sold_id = fields.Many2one(
        'sale.contract',
        string='Sale Contract',
        readonly=True,
        help='Related sale contract'
    )
    
    sold_property_id = fields.Many2one(
        'property.details',
        string='Sold Property',
        related='sold_id.property_id',
        store=True,
        readonly=True
    )

    project_id = fields.Many2one(
        'property.project',
        string='Project',
        compute='_compute_property_unit_links',
        store=True,
        readonly=True,
    )

    property_id = fields.Many2one(
        'property.details',
        string='Unit',
        compute='_compute_property_unit_links',
        store=True,
        readonly=True,
    )

    property_unit_no = fields.Char(
        string='Unit No.',
        related='property_id.unit_number',
        store=True,
        readonly=True,
        help='Unit number of the property linked to this invoice (e.g. 201).',
    )

    maintenance_request_id = fields.Many2one(
        'maintenance.request',
        string='Maintenance Request',
        readonly=True,
        help='Related maintenance request'
    )

    @api.depends('sold_id', 'tenancy_id')
    def _compute_property_unit_links(self):
        for move in self:
            if move.sold_id and move.sold_id.property_id:
                move.project_id = move.sold_id.property_id.project_id
                move.property_id = move.sold_id.property_id
            elif move.tenancy_id and move.tenancy_id.property_id:
                move.project_id = move.tenancy_id.property_id.project_id
                move.property_id = move.tenancy_id.property_id
            else:
                move.project_id = False
                move.property_id = False

    def action_view_sold_contract(self):
        self.ensure_one()
        if not self.sold_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'name': 'Sale Contract',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.contract',
            'view_mode': 'form',
            'res_id': self.sold_id.id,
            'target': 'current',
        }

    def action_view_tenancy(self):
        self.ensure_one()
        if not self.tenancy_id:
            return {'type': 'ir.actions.act_window_close'}
        return {
            'name': 'Tenancy',
            'type': 'ir.actions.act_window',
            'res_model': 'tenancy.details',
            'view_mode': 'form',
            'res_id': self.tenancy_id.id,
            'target': 'current',
        }

    def action_view_payments(self):
        self.ensure_one()
        payment_ids = self._get_reversal_or_original_payment_ids()
        return {
            'name': 'Payments',
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', payment_ids.ids)],
            'target': 'current',
        }

    def _get_reversal_or_original_payment_ids(self):
        payments = self.env['account.payment']
        if self.move_type in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
            payments = payments.search([
                ('invoice_ids', '=', self.id),
                ('state', 'in', ('posted', 'in_process', 'paid')),
            ])
        return payments
