# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import UserError


UNIT_TYPE_SELECTION = [
    ('studio', 'Studio'),
    ('1br', '1 Bedroom'),
    ('2br', '2 Bedrooms'),
    ('3br', '3 Bedrooms'),
    ('4br', '4 Bedrooms'),
    ('penthouse', 'Penthouse'),
]
UNIT_TYPE_LABELS = dict(UNIT_TYPE_SELECTION)


class UnitCreationMix(models.TransientModel):
    _name = 'unit.creation.mix'
    _description = 'Unit Mix Line (bulk creation)'
    _order = 'id'

    wizard_id = fields.Many2one('unit.creation', string='Wizard',
                                required=True, ondelete='cascade')
    unit_type = fields.Selection(UNIT_TYPE_SELECTION, string='Unit Type',
                                 required=True)
    count = fields.Integer(string='Count', default=1, required=True)


class UnitCreation(models.TransientModel):
    _name = 'unit.creation'
    _description = 'Project Unit Creation'

    total_floors = fields.Integer(string="Floors in This Batch",
                                  default=1, required=True,
                                  help="How many new floors to create with this run.")
    units_per_floor = fields.Integer(string="Units per Floor",
                                     default=1, required=True)
    floor_start_from = fields.Integer(string="First Floor Number", default=1,
                                      help="Wizard continues numbering from the "
                                           "project's next unused floor by default.")
    unit_code_prefix = fields.Char(string="Prefix",
                                   help="Prefix for the Property Code, e.g. PARKR. "
                                        "Code = Prefix-FloorUnit, e.g. PARKR-0101.")
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    default_price = fields.Monetary(string="Default Price",
                                    currency_field='currency_id',
                                    help="Optional price applied to every unit "
                                         "created by this run.")
    default_area = fields.Float(string="Default Area (sq ft)",
                                help="Optional area applied to every unit "
                                     "created by this run.")
    unit_mix_ids = fields.One2many('unit.creation.mix', 'wizard_id',
                                  string='Unit Mix',
                                  help="Optional split of the units on each floor. "
                                       "The counts must equal Units per Floor.")
    total_unit_count = fields.Integer(string='Units to Create',
                                     compute='_compute_total_unit_count')

    @api.depends('total_floors', 'units_per_floor')
    def _compute_total_unit_count(self):
        for rec in self:
            rec.total_unit_count = (rec.total_floors or 0) * (rec.units_per_floor or 0)

    def _get_owner(self):
        """Return the property.project / property.sub.project this wizard runs from.

        Works on an empty recordset too (default_get context), so no
        ensure_one() here.
        """
        active_id = self._context.get('active_id')
        unit_from = self._context.get('unit_from')
        if not active_id:
            return False
        if unit_from == 'project':
            return self.env['property.project'].browse(int(active_id))
        if unit_from == 'sub_project':
            return self.env['property.sub.project'].browse(int(active_id))
        return False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        owner = self._get_owner()
        if owner and owner.id:
            if owner.code:
                res.setdefault('unit_code_prefix', owner.code)
            if owner.units_per_floor:
                res.setdefault('units_per_floor', owner.units_per_floor)
            res['floor_start_from'] = (owner.floor_created or 0) + 1
        return res

    def _per_floor_mix(self):
        """Expand the unit mix into an ordered list of unit types (one per slot)."""
        self.ensure_one()
        slots = []
        for line in self.unit_mix_ids.sorted('id'):
            slots.extend([line.unit_type] * (line.count or 0))
        return slots

    def action_create_units(self):
        """Bulk-create property.details units (floors x units-per-floor)."""
        self.ensure_one()
        if self.total_floors <= 0:
            raise UserError(_('Total floors must be greater than 0.'))
        if self.units_per_floor <= 0:
            raise UserError(_('Units per floor must be greater than 0.'))
        owner = self._get_owner()
        if not owner or not owner.id:
            raise UserError(_('Open this wizard from a Project or Sub-Project form.'))
        mix_total = sum(self.unit_mix_ids.mapped('count'))
        if mix_total and mix_total != self.units_per_floor:
            raise UserError(_(
                "The unit mix counts to %(mix)d but Units per Floor is %(upf)d. "
                "Both must match."
            ) % {'mix': mix_total, 'upf': self.units_per_floor})

        per_floor = self._per_floor_mix()
        start_floor = self.floor_start_from or 1
        prefix = self.unit_code_prefix or owner.code or 'U'
        is_sub = owner._name == 'property.sub.project'

        # Guard against code collisions (e.g. a re-run with the same prefix).
        generated = set()
        for offset in range(self.total_floors):
            for idx in range(1, self.units_per_floor + 1):
                generated.add('%s-%d%02d' % (prefix, start_floor + offset, idx))
        existing = set(self.env['property.details'].search([
            ('property_code', 'in', list(generated)),
        ]).mapped('property_code'))
        if existing:
            raise UserError(_(
                "Property codes already exist: %(codes)s. Change the prefix or "
                "the starting floor."
            ) % {'codes': ', '.join(sorted(existing))})

        # Static values copied from the owning project / sub-project.
        static_vals = {
            'company_id': owner.company_id.id,
            'region_id': owner.region_id.id or False,
            'sale_lease': owner.sale_lease or False,
            'address': owner.address or False,
            'city': owner.city or False,
            'state_id': owner.state_id.id or False,
            'country_id': owner.country_id.id or False,
            'zip': owner.zip or False,
            'price': self.default_price or False,
            'area': self.default_area or False,
            'state': 'available',
            'property_type': 'residential',
        }
        if is_sub:
            static_vals['project_id'] = owner.project_id.id
            static_vals['sub_project_id'] = owner.id
        else:
            static_vals['project_id'] = owner.id
        if owner.payment_schedule_id:
            static_vals['is_payment_plan'] = True
            static_vals['payment_schedule_id'] = owner.payment_schedule_id.id

        data = []
        for offset in range(self.total_floors):
            floor = start_floor + offset
            for idx in range(1, self.units_per_floor + 1):
                unit_type = per_floor[idx - 1] if per_floor else False
                unit_number = '%d%02d' % (floor, idx)
                type_label = UNIT_TYPE_LABELS.get(unit_type, 'Unit')
                data.append(dict(
                    static_vals,
                    name='%s - %s %s' % (owner.name, type_label, unit_number),
                    property_code='%s-%s' % (prefix, unit_number),
                    floor=floor,
                    unit_number=unit_number,
                    unit_type=unit_type or False,
                ))

        created = self.env['property.details'].create(data)

        # Advance the owner's layout counters so the next run continues
        # numbering from the next floor.
        owner.write({
            'floor_created': (owner.floor_created or 0) + self.total_floors,
            'total_floors': (owner.floor_created or 0) + self.total_floors,
            'units_per_floor': self.units_per_floor,
        })
        return {
            "name": _("Properties (%(count)d created)") % {'count': len(created)},
            "type": "ir.actions.act_window",
            "domain": [("id", "in", created.ids)],
            "view_mode": "list,form",
            "res_model": "property.details",
            "target": "current",
        }
