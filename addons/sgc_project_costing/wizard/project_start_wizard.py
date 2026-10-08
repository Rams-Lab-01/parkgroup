# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Wizard that creates the project's analytic account and sets its budget."""

from odoo import api, fields, models, _


class ProjectStartWizard(models.TransientModel):
    """Create the analytic account for a project and record its budget."""

    _name = 'project.start.wizard'
    _description = 'Project Start Wizard - Create Analytic Account'

    project_id = fields.Many2one('property.project', required=True)
    currency_id = fields.Many2one(
        'res.currency', related='project_id.currency_id', readonly=True,
    )
    budget = fields.Monetary(
        string='Project Budget', currency_field='currency_id',
        help='Total approved budget for this development project.',
    )

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        project = self._default_project()
        if project:
            defaults.setdefault('project_id', project.id)
            defaults.setdefault('budget', project.project_budget or 0.0)
        return defaults

    def _default_project(self):
        context = self.env.context
        project_id = context.get('default_project_id') or context.get('active_id')
        if project_id:
            return self.env['property.project'].browse(project_id).exists()
        return self.env['property.project']

    def action_start(self):
        """Create the analytic account (if needed) and set the budget."""
        self.ensure_one()
        project = self.project_id
        project.project_budget = self.budget
        if not project.project_analytic_account_id:
            account = self.env['account.analytic.account'].create({
                'name': '%s (%s)' % (project.name, project.code or project.id),
                'plan_id': self._get_default_plan().id,
                'company_id': project.company_id.id or self.env.company.id,
                'code': project.code or False,
            })
            project.project_analytic_account_id = account
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'property.project',
            'res_id': project.id,
            'view_mode': 'form',
        }

    def _get_default_plan(self):
        """Return (creating if needed) the analytic plan costs roll under."""
        Plan = self.env['account.analytic.plan']
        plan = Plan.search([('name', '=', 'Property Development')], limit=1)
        if not plan:
            plan = Plan.create({'name': 'Property Development'})
        return plan
