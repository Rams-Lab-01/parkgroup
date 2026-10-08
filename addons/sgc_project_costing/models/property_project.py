# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Project costing overlay on ``property.project``.

Mirrors the escrow module: every financial figure is a *query* over the
standard analytic ledger (``account.analytic.line``) and the purchase
commitments that carry an analytic distribution. There is no shadow subledger.

Odoo 19 analytic model reference (verified against the deployed schema):

* ``account.analytic.account`` links to a ``plan_id`` (there is no ``type`` and
  no ``parent_id`` on accounts; plans are the hierarchy).
* ``account.analytic.line`` is linked by ``account_id`` and holds ``amount``.
* Purchase order lines carry a JSON ``analytic_distribution`` and the searchable
  helper ``distribution_analytic_account_ids`` -- there is no single
  ``analytic_account_id`` on ``purchase.order.line`` any more.
"""

from odoo import api, fields, models, _


class PropertyProjectCosting(models.Model):
    """Project costing overlay on property.project."""

    _inherit = 'property.project'

    # ---------- Core field declarations ----------
    currency_id = fields.Many2one(
        'res.currency',
        string='Project Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
        help='Currency of the project (from the company).',
    )

    project_analytic_account_id = fields.Many2one(
        'account.analytic.account',
        string='Analytic Account',
        tracking=True,
        help='Analytic account linked to this project for cost tracking.',
    )

    # ---------- Budget & costing ----------
    project_budget = fields.Monetary(
        string='Project Budget',
        currency_field='currency_id',
        default=0.0,
        tracking=True,
        help='Total approved budget for this development project.',
    )
    analytic_account_budget = fields.Monetary(
        string='Budgeted (Analytic)',
        currency_field='currency_id',
        compute='_compute_budget_totals',
        help='Budget recorded on the analytic account.',
    )
    analytic_costed = fields.Monetary(
        string='Costed',
        currency_field='currency_id',
        compute='_compute_budget_totals',
        help='Sum of analytic lines (actual costs) posted to this project.',
    )
    analytic_committed = fields.Monetary(
        string='Committed',
        currency_field='currency_id',
        compute='_compute_budget_totals',
        help='Sum of confirmed purchase order lines carrying this project on '
             'their analytic distribution.',
    )
    analytic_remaining = fields.Monetary(
        string='Remaining',
        currency_field='currency_id',
        compute='_compute_budget_totals',
        help='Budget minus actual cost.',
    )

    # ---------- Collection timeline ----------
    expected_collections = fields.Monetary(
        string='Expected Collections',
        currency_field='currency_id',
        compute='_compute_collection_timeline',
        help='Sum of planned collection milestones.',
    )
    actual_collections = fields.Monetary(
        string='Actual Collections',
        currency_field='currency_id',
        compute='_compute_collection_timeline',
        help='Sum of collection milestones actually collected.',
    )
    collection_variance = fields.Monetary(
        string='Collection Variance',
        currency_field='currency_id',
        compute='_compute_collection_timeline',
        help='Actual collections minus expected.',
    )

    # ---------- Project health ----------
    cash_position = fields.Monetary(
        string='Cash Position',
        currency_field='currency_id',
        compute='_compute_project_health',
        help='Actual collections minus actual costs.',
    )
    burn_rate = fields.Float(
        string='Burn Rate (%)',
        compute='_compute_project_health',
        help='Actual costs as a percentage of budget.',
    )
    budget_variance = fields.Monetary(
        string='Budget Variance',
        currency_field='currency_id',
        compute='_compute_project_health',
        help='Budget minus actual cost.',
    )
    budget_variance_percent = fields.Float(
        string='Budget Variance %',
        compute='_compute_project_health',
        help='Variance as a percentage of budget.',
    )

    # ---------- Milestones ----------
    cost_milestone_ids = fields.One2many(
        'project.cost.milestone', 'project_id', string='Cost Milestones',
        help='Planned and actual cost / collection milestones.',
    )
    cost_milestone_count = fields.Integer(
        string='Milestones', compute='_compute_cost_milestone_count',
    )

    # ---------- Computes ----------
    @api.depends('cost_milestone_ids')
    def _compute_cost_milestone_count(self):
        for project in self:
            project.cost_milestone_count = len(project.cost_milestone_ids)

    @api.depends(
        'project_budget',
        'project_analytic_account_id',
    )
    def _compute_budget_totals(self):
        AnalyticLine = self.env['account.analytic.line']
        PurchaseLine = self.env['purchase.order.line']
        for project in self:
            account = project.project_analytic_account_id
            # ``account.line_ids`` does not reliably expose every analytic line
            # in Odoo 19 (its o2m inverse is not ``account_id``), so query the
            # ledger directly by ``account_id``.
            costed = sum(AnalyticLine.search([
                ('account_id', '=', account.id),
            ]).mapped('amount')) if account else 0.0
            committed = 0.0
            if account:
                po_lines = PurchaseLine.search([
                    ('distribution_analytic_account_ids', 'in', account.ids),
                    ('order_id.state', 'in', ('purchase', 'done')),
                ])
                for line in po_lines:
                    distribution = line.analytic_distribution or {}
                    # Keys of analytic_distribution are stringified account ids.
                    percentage = distribution.get(str(account.id), 0.0) or 0.0
                    committed += line.price_subtotal * percentage / 100.0
            project.analytic_account_budget = project.project_budget
            project.analytic_costed = costed
            project.analytic_committed = committed
            project.analytic_remaining = project.project_budget - costed

    @api.depends(
        'cost_milestone_ids.milestone_type',
        'cost_milestone_ids.planned_amount',
        'cost_milestone_ids.actual_amount',
    )
    def _compute_collection_timeline(self):
        for project in self:
            collections = project.cost_milestone_ids.filtered(
                lambda m: m.milestone_type == 'collection')
            expected = sum(collections.mapped('planned_amount'))
            actual = sum(collections.mapped('actual_amount'))
            project.expected_collections = expected
            project.actual_collections = actual
            project.collection_variance = actual - expected

    @api.depends('actual_collections', 'analytic_costed', 'project_budget')
    def _compute_project_health(self):
        for project in self:
            costs = project.analytic_costed or 0.0
            budget = project.project_budget or 0.0
            collections = project.actual_collections or 0.0
            project.cash_position = collections - costs
            project.burn_rate = (costs / budget * 100.0) if budget else 0.0
            project.budget_variance = budget - costs
            project.budget_variance_percent = (
                ((budget - costs) / budget * 100.0) if budget else 0.0
            )

    # ---------- Navigation actions ----------
    def get_recent_analytic_lines(self, limit=20):
        """Recent analytic lines for the report template (search-based, since
        ``account.analytic.account.line_ids`` is unreliable in Odoo 19)."""
        self.ensure_one()
        if not self.project_analytic_account_id:
            return self.env['account.analytic.line']
        return self.env['account.analytic.line'].search(
            [('account_id', '=', self.project_analytic_account_id.id)],
            order='date desc, id desc', limit=limit,
        )

    def action_view_analytic_account(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Analytic Account'),
            'res_model': 'account.analytic.account',
            'view_mode': 'form',
        }
        if self.project_analytic_account_id:
            action['res_id'] = self.project_analytic_account_id.id
        else:
            action['view_mode'] = 'list,form'
        return action

    def action_view_analytic_lines(self):
        self.ensure_one()
        domain = [('account_id', '=', self.project_analytic_account_id.id)]
        return {
            'type': 'ir.actions.act_window',
            'name': _('Analytic Lines'),
            'res_model': 'account.analytic.line',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {'search_default_group_by_account': 1},
        }

    def action_view_cost_milestones(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cost Milestones'),
            'res_model': 'project.cost.milestone',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_open_collection_timeline(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Collection Timeline'),
            'res_model': 'project.cost.milestone',
            'view_mode': 'list,form',
            'domain': [
                ('project_id', '=', self.id),
                ('milestone_type', '=', 'collection'),
            ],
            'context': {'default_project_id': self.id, 'default_milestone_type': 'collection'},
        }

    def action_open_cost_report(self):
        self.ensure_one()
        return self.env.ref(
            'sgc_project_costing.action_report_project_cost'
        ).report_action(self)

    def action_open_project_start_wizard(self):
        """Open the wizard that creates the analytic account and sets the budget."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Set Budget & Analytic Account'),
            'res_model': 'project.start.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'active_id': self.id, 'default_project_id': self.id},
        }
