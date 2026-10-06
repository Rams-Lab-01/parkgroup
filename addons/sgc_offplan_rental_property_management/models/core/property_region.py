# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

from odoo import api, models, fields


class PropertyRegion(models.Model):
    _name = "property.region"
    _inherit = ["mail.thread", "mail.activity.mixin", "sgc.critical.audit.mixin"]
    _description = "Property Regions"

    name = fields.Char(string="Region")
    city_ids = fields.Many2many('property.res.city', string="Cities")
    project_count = fields.Integer(string="Project Count",
                                   compute="compute_count")
    subproject_count = fields.Integer(string="Subproject Count",
                                      compute="compute_count")
    unit_count = fields.Integer(string="Units Count",
                                compute="compute_count")

    def compute_count(self):
        for rec in self:
            rec.project_count = self.env['property.project'].search_count(
                [('region_id', '=', rec.id)])
            rec.subproject_count = self.env['property.sub.project'].search_count(
                [('region_id', '=', rec.id)])
            rec.unit_count = self.env['property.details'].search_count(
                [('region_id', '=', rec.id)])

    def action_view_project(self):
        return {
            "name": "Projects",
            "type": "ir.actions.act_window",
            "domain": [("region_id", "=", self.id)],
            "view_mode": "list,form",
            'context': {'create': False},
            "res_model": "property.project",
            "target": "current",
        }

    def action_view_sub_project(self):
        return {
            "name": "Sub Projects",
            "type": "ir.actions.act_window",
            "domain": [("region_id", "=", self.id)],
            "view_mode": "list,form",
            'context': {'create': False},
            "res_model": "property.sub.project",
            "target": "current",
        }

    def action_view_properties(self):
        return {
            "name": "Units",
            "type": "ir.actions.act_window",
            "domain": [("region_id", "=", self.id)],
            "view_mode": "list,form",
            'context': {'create': False},
            "res_model": "property.details",
            "target": "current",
        }
