# -*- coding: utf-8 -*-

from odoo import models, api


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    def action_view_sale_contract(self):
        self.ensure_one()
        if not self.invoice_ids:
            return {'type': 'ir.actions.act_window_close'}
        first_inv = self.invoice_ids[0]
        if first_inv.sold_id:
            return {
                'name': 'Sale Contract',
                'type': 'ir.actions.act_window',
                'res_model': 'sale.contract',
                'view_mode': 'form',
                'res_id': first_inv.sold_id.id,
                'target': 'current',
            }
        return {'type': 'ir.actions.act_window_close'}

    def action_view_tenancy(self):
        self.ensure_one()
        if not self.invoice_ids:
            return {'type': 'ir.actions.act_window_close'}
        first_inv = self.invoice_ids[0]
        if first_inv.tenancy_id:
            return {
                'name': 'Tenancy',
                'type': 'ir.actions.act_window',
                'res_model': 'tenancy.details',
                'view_mode': 'form',
                'res_id': first_inv.tenancy_id.id,
                'target': 'current',
            }
        return {'type': 'ir.actions.act_window_close'}
