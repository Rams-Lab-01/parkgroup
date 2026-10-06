# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ActiveContract(models.TransientModel):
    _name = 'rent.active.contract'
    _description = 'Active Contract'

    contract_id = fields.Many2one('rent.contract', string='Contract')

    def action_activate(self):
        return {'type': 'ir.actions.act_window_close'}
