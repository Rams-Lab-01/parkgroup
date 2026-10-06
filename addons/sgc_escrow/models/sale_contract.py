# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Escrow visibility on ``sale.contract``.

The contract is the natural home for "what has this buyer paid into escrow and
what is still outstanding". Nothing here posts anything -- it only reads the
allocation register and the ledger.
"""

from odoo import api, fields, models


class SaleContractEscrow(models.Model):
    _inherit = 'sale.contract'

    escrow_project_id = fields.Many2one(
        'property.project',
        string='Escrow Project',
        related='property_id.project_id',
        store=True,
        readonly=True,
        index=True,
    )
    escrow_allocation_ids = fields.One2many(
        'escrow.allocation',
        'contract_id',
        string='Escrow Allocations',
    )
    escrow_allocation_count = fields.Integer(
        string='Escrow Allocation Rows',
        compute='_compute_escrow_allocation_count',
    )
    escrow_amount_allocated = fields.Monetary(
        string='In Escrow (per Source)',
        currency_field='currency_id',
        compute='_compute_escrow_allocation_count',
        help='Escrow allocation recorded for this contract, per the source document.',
    )
    escrow_amount_required = fields.Monetary(
        string='Required by Escrow Rules',
        currency_field='currency_id',
        compute='_compute_escrow_allocation_count',
        help='Sale price x escrow % required to be held for this contract.',
    )
    escrow_amount_variance = fields.Monetary(
        string='Escrow Variance',
        currency_field='currency_id',
        compute='_compute_escrow_allocation_count',
        help='Allocated less required. Non-zero means the source and the escrow '
             'rules disagree and finance has to sign off.',
    )

    @api.depends('escrow_allocation_ids')
    def _compute_escrow_allocation_count(self):
        for record in self:
            allocations = record.escrow_allocation_ids
            record.escrow_allocation_count = len(allocations)
            record.escrow_amount_allocated = sum(allocations.mapped('allocated_amount'))
            record.escrow_amount_required = sum(allocations.mapped('required_amount'))
            record.escrow_amount_variance = sum(allocations.mapped('variance_amount'))

    def action_view_escrow_allocations(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'sgc_escrow.action_escrow_allocation')
        action['domain'] = [('contract_id', '=', self.id)]
        action['context'] = {'default_contract_id': self.id}
        if len(action['domain']) == 1:
            action['domain'] = [('id', 'in', self.escrow_allocation_ids.ids)]
        return action