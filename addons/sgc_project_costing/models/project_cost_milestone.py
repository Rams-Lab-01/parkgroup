# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Milestone model for cost & collection timelines."""

from odoo import api, fields, models


class ProjectCostMilestone(models.Model):
    """Cost / collection milestone tied to a property.project."""

    _name = 'project.cost.milestone'
    _description = 'Project Cost Milestone / Collection Timeline'
    _order = 'planned_date, id'

    project_id = fields.Many2one(
        'property.project', string='Project', required=True, ondelete='cascade',
        help='Project this milestone belongs to.',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='project_id.currency_id',
        store=True,
        readonly=True,
    )
    name = fields.Char(
        string='Milestone', required=True,
        help='Short name / description of the milestone.',
    )
    milestone_type = fields.Selection([
        ('cost', 'Cost Milestone'),
        ('collection', 'Collection Milestone'),
    ], default='cost', required=True,
        help='Whether this is a planned cost outflow or a collection inflow.')
    planned_date = fields.Date(
        string='Planned Date', required=True,
        help='The date this milestone was planned for.',
    )
    actual_date = fields.Date(
        string='Actual Date',
        help='Date the milestone actually occurred (empty if pending).',
    )
    planned_amount = fields.Monetary(
        string='Planned Amount', currency_field='currency_id',
        help='Planned amount for this milestone.',
    )
    actual_amount = fields.Monetary(
        string='Actual Amount', currency_field='currency_id',
        help='Actual amount collected or spent.',
    )
    variance = fields.Monetary(
        string='Variance', currency_field='currency_id',
        compute='_compute_variance', store=True,
        help='Actual - Planned; negative = under, positive = over.',
    )
    is_completed = fields.Boolean(
        string='Completed', default=False,
        help='Tick once the actual date and amount are recorded.',
    )
    notes = fields.Text(
        string='Notes', help='Additional context / reason for variance.',
    )

    @api.depends('actual_amount', 'planned_amount')
    def _compute_variance(self):
        for milestone in self:
            milestone.variance = (
                (milestone.actual_amount or 0.0) - (milestone.planned_amount or 0.0)
            )
