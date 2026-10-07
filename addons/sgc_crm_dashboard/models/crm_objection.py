# -*- coding: utf-8 -*-
################################################################################
#
#    Cybrosys Technologies Pvt. Ltd.
#
#    Copyright (C) 2023-TODAY Cybrosys Technologies(<https://www.cybrosys.com>).
#    Author:  Mruthul Raj (odoo@cybrosys.com)
#
#    You can modify it under the terms of the GNU AFFERO
#    GENERAL PUBLIC LICENSE (AGPL v3), Version 3.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY OR FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU AFFERO GENERAL PUBLIC LICENSE (AGPL v3) for more details.
#
#    You should have received a copy of the GNU AFFERO GENERAL PUBLIC LICENSE
#    (AGPL v3) along with this program.
#    If not, see <http://www.gnu.org/licenses/>.
#
################################################################################
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class CrmObjection(models.Model):
    _name = 'crm.objection'
    _description = 'CRM Objection'
    _order = 'name'

    name = fields.Char(string='Objection', required=True, translate=True, size=40)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    _sql_constraints = [
        ('name_uniq', 'unique (name)', 'Objection name must be unique!'),
    ]

    @api.constrains('name')
    def _check_name_short(self):
        for rec in self:
            if not rec.name:
                continue
            if len(rec.name) > 40:
                raise ValidationError(_(
                    "Objection must be 40 characters or less. "
                    "Keep it short — put details in the lead's notes."))
            if len(rec.name.split()) > 5:
                raise ValidationError(_(
                    "Objection must be 5 words or less (e.g. 'Too Expensive'). "
                    "Put the full explanation in the lead's notes instead."))


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    objection_ids = fields.Many2many(
        'crm.objection',
        'crm_lead_objection_rel',
        'lead_id',
        'objection_id',
        string='Objections',
        help="Objections raised by the lead during the sales process"
    )
