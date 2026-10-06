# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SubprojectCreation(models.TransientModel):
    _name = "subproject.creation"
    _description = "Create Sub Project"

    name = fields.Char(string="Name", required=True)
    code = fields.Char(string="Code", required=True,
                       help="Sub-project code, e.g. PARKR-TA. Used as the "
                            "default prefix for units created from it.")
    total_floors = fields.Integer(string="No. of Floors")
    units_per_floor = fields.Integer(string="Units per Floor")
    sale_lease = fields.Selection([
        ('sale', 'Sale'),
        ('lease', 'Lease'),
        ('both', 'Both'),
    ], string='Sale/Lease')
    payment_schedule_id = fields.Many2one('payment.schedule',
                                          string='Installment Plan')
    region_id = fields.Many2one('property.region', string='Region')
    address = fields.Text(string="Address")
    city = fields.Char(string="City")
    state_id = fields.Many2one('res.country.state', string="State")
    country_id = fields.Many2one('res.country', string="Country")
    zip = fields.Char(string="ZIP")
    copy_parent_image = fields.Boolean(string="Copy Parent Project Image",
                                       default=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self._context.get('active_id')
        if active_id:
            project = self.env['property.project'].browse(active_id)
            if project.id:
                if not res.get('code'):
                    res['code'] = '%s-SP' % (project.code or project.name[:8])
                res.setdefault('sale_lease', project.sale_lease or False)
                res.setdefault('payment_schedule_id',
                               project.payment_schedule_id.id or False)
                res.setdefault('region_id', project.region_id.id or False)
                res.setdefault('address', project.address or False)
                res.setdefault('city', project.city or False)
                res.setdefault('state_id', project.state_id.id or False)
                res.setdefault('country_id', project.country_id.id or False)
                res.setdefault('zip', project.zip or False)
        return res

    def create_sub_project(self):
        self.ensure_one()
        active_id = self._context.get('active_id')
        if not active_id:
            raise UserError(_('Open this wizard from a Project form.'))
        project = self.env['property.project'].browse(active_id)
        data = {
            'name': self.name,
            'code': self.code,
            'project_id': project.id,
            'company_id': project.company_id.id,
            'total_floors': self.total_floors or 0,
            'units_per_floor': self.units_per_floor or 0,
            'sale_lease': self.sale_lease or project.sale_lease or False,
            'payment_schedule_id': self.payment_schedule_id.id
                                   or project.payment_schedule_id.id
                                   or False,
            'region_id': self.region_id.id or project.region_id.id or False,
            'address': self.address or project.address or False,
            'city': self.city or project.city or False,
            'state_id': self.state_id.id or project.state_id.id or False,
            'country_id': self.country_id.id or project.country_id.id or False,
            'zip': self.zip or project.zip or False,
        }
        sub_project_id = self.env['property.sub.project'].create(data)
        if self.copy_parent_image and project.image_1920:
            sub_project_id.image_1920 = project.image_1920
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sub Projects'),
            'res_model': 'property.sub.project',
            'res_id': sub_project_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
