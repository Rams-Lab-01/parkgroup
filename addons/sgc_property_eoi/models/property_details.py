from odoo import _, api, fields, models
from odoo.exceptions import UserError

# Set by the explicit "cancel a confirmed sale" workflow only. Without it a Confirmed Sale can never be released.
CTX_RELEASE = 'sgc_release_confirmed_sale'
CTX_SKIP_GUARD = 'sgc_skip_state_guard'


class PropertyDetails(models.Model):
    _inherit = 'property.details'

    # Full list re-declared (not selection_add) so the sales lifecycle reads in business order:
    # Available -> EOI -> Booked -> Confirmed Sale -> Sold.  tests/test_workflow.py asserts that every legacy
    # key is still present, so a change in the base module cannot silently drop a status.
    state = fields.Selection(selection=[
        ('available', 'Available'),
        ('eoi', 'EOI'),
        ('booked', 'Booked'),
        ('confirmed_sale', 'Confirmed Sale'),
        ('sold', 'Sold'),
        ('rented', 'Rented'),
        ('maintenance', 'Under Maintenance'),
    ])
    parking = fields.Char(string='Parking')
    view_description = fields.Char(string='View')

    eoi_ids = fields.One2many('property.eoi', 'property_id', string='EOIs')
    eoi_count = fields.Integer(compute='_compute_sales_counts')
    booking_ids = fields.One2many('property.vendor', 'property_id', string='Bookings')
    booking_count = fields.Integer(compute='_compute_sales_counts')
    active_eoi_id = fields.Many2one('property.eoi', compute='_compute_sales_counts', string='Active EOI')

    @api.depends('eoi_ids.state', 'booking_ids')
    def _compute_sales_counts(self):
        for rec in self:
            rec.eoi_count = len(rec.eoi_ids)
            rec.booking_count = len(rec.booking_ids)
            rec.active_eoi_id = rec.eoi_ids.filtered(lambda e: e.state == 'active')[:1]

    # ------------------------------------------------------------------ status guard
    def _sgc_check_transition(self, new_state):
        """Business rules for the sales statuses. Everything not listed here is left to the base module."""
        ctx = self.env.context
        if ctx.get(CTX_SKIP_GUARD):
            return
        for rec in self:
            old = rec.state
            if old == new_state:
                continue
            if new_state == 'eoi' and old != 'available':
                raise UserError(_('%(unit)s is "%(old)s" - only an Available unit can be placed under EOI.',
                                  unit=rec.display_name, old=rec._sgc_state_label(old)))
            if old == 'eoi' and new_state not in ('available', 'booked'):
                raise UserError(_('%(unit)s is under EOI. It can only return to Available (EOI cancelled) or '
                                  'move to Booked (EOI converted).', unit=rec.display_name))
            if new_state == 'confirmed_sale' and old != 'booked':
                raise UserError(_('%(unit)s must be Booked before the sale can be confirmed.', unit=rec.display_name))
            if old == 'confirmed_sale' and new_state in ('available', 'booked', 'eoi') and not ctx.get(CTX_RELEASE):
                raise UserError(_('%(unit)s is a Confirmed Sale and cannot be released directly. Use "Cancel '
                                  'Confirmed Sale" on the booking (manager action, reason required).',
                                  unit=rec.display_name))

    def _sgc_state_label(self, key):
        return dict(self._fields['state']._description_selection(self.env)).get(key, key)

    def write(self, vals):
        if 'state' in vals:
            self._sgc_check_transition(vals['state'])
        return super().write(vals)

    # ------------------------------------------------------------------ smart buttons / actions
    def action_register_eoi(self):
        self.ensure_one()
        if self.state != 'available':
            raise UserError(_('Only an Available unit can receive an EOI (status: %s).', self._sgc_state_label(self.state)))
        return {
            'type': 'ir.actions.act_window', 'name': _('New EOI'), 'res_model': 'property.eoi',
            'view_mode': 'form', 'target': 'current',
            'context': {'default_property_id': self.id},
        }

    def action_view_eois(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('sgc_property_eoi.action_property_eoi')
        action['domain'] = [('property_id', '=', self.id)]
        action['context'] = {'default_property_id': self.id, 'search_default_property_id': self.id}
        return action

    def action_view_bookings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _('Bookings'), 'res_model': 'property.vendor',
            'view_mode': 'list,form', 'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id},
        }

    @api.model
    def get_property_stats(self):
        """Base dashboard KPIs untouched; the two new lifecycle stages are added as extra keys."""
        stats = super().get_property_stats()
        groups = self.sudo()._read_group(
            [('company_id', 'in', self.env.companies.ids), ('state', 'in', ('eoi', 'confirmed_sale'))],
            groupby=['state'], aggregates=['__count'])
        counts = dict(groups)
        stats['eoi_property'] = counts.get('eoi', 0)
        stats['confirmed_sale_property'] = counts.get('confirmed_sale', 0)
        return stats
