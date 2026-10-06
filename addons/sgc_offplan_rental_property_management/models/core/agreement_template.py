# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AgreementTemplate(models.Model):
    _name = 'agreement.template'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _description = 'Agreement Template'
    _order = 'name'

    name = fields.Char(string='Template Name', required=True)
    description = fields.Text(string='Description')
    content = fields.Html(string='Content')
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    model = fields.Char(string='Related Model')
    agreement = fields.Html(string='Agreement', required=True)
    template_variable_ids = fields.One2many(
        'agreement.template.variable', 'template_id', string='Template Variables'
    )

    def action_preview(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Preview Agreement',
            'res_model': 'agreement.template',
            'view_mode': 'form',
            'res_id': self.id,
            'target': 'new',
        }


class AgreementTemplateVariable(models.Model):
    _name = 'agreement.template.variable'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Agreement Template Variable'
    _order = 'name'

    # Entry 52 scope: how a template resolves its variables. Line -> exempt.
    _audit_watched_fields = frozenset({
        'template_id', 'name', 'field_type', 'model', 'field_name',
        'free_text', 'demo',
    })
    _audit_unlink_requires_reason = False

    template_id = fields.Many2one('agreement.template', string='Template', required=True, ondelete='cascade')
    name = fields.Char(string='Variable Name', required=True)
    field_type = fields.Selection([
        ('field', 'Field'),
        ('free_text', 'Free Text'),
    ], string='Field Type', required=True, default='field')
    model = fields.Char(string='Model')
    field_name = fields.Char(string='Field Name')
    free_text = fields.Char(string='Free Text')
    demo = fields.Char(string='Demo Value')
