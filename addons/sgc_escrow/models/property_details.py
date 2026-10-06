# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Escrow visibility on ``property.details`` (the unit).

The unit is the record the sales team actually works with, so the escrow tab
lives here: what the buyer owes, what the escrow rules require to be held, and
what the source says is sitting in escrow.
"""

from odoo import api, fields, models


class PropertyDetailsEscrow(models.Model):
    _inherit = 'property.details'

    escrow_allocation_ids = fields.One2many(
        'escrow.allocation',
        'unit_id',
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
        help='Escrow allocation recorded for this unit, per the source document.',
    )
    escrow_amount_required = fields.Monetary(
        string='Required by Escrow Rules',
        currency_field='currency_id',
        compute='_compute_escrow_allocation_count',
    )
    escrow_amount_variance = fields.Monetary(
        string='Escrow Variance',
        currency_field='currency_id',
        compute='_compute_escrow_allocation_count',
        help='Allocated less required. Non-zero means the source and the escrow '
             'rules disagree and finance has to sign off.',
    )
    escrow_has_source_data = fields.Boolean(
        string='Source Allocation On File',
        compute='_compute_escrow_allocation_count',
        help='False when the source carried no escrow allocation figure for this '
             'unit. Such units are reported, never treated as zero.',
    )
    escrow_flag_code = fields.Char(
        string='Escrow Flag',
        compute='_compute_escrow_allocation_count',
        help='Open reconciliation flag awaiting finance sign-off.',
    )

    @api.depends('escrow_allocation_ids')
    def _compute_escrow_allocation_count(self):
        for record in self:
            allocations = record.escrow_allocation_ids
            record.escrow_allocation_count = len(allocations)
            record.escrow_amount_allocated = sum(allocations.mapped('allocated_amount'))
            record.escrow_amount_required = sum(allocations.mapped('required_amount'))
            record.escrow_amount_variance = sum(allocations.mapped('variance_amount'))
            record.escrow_has_source_data = any(
                allocations.mapped('has_source_data'))
            record.escrow_flag_code = ', '.join(
                sorted({a.flag_code for a in allocations if a.flag_code}))