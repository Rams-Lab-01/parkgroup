import logging

from odoo import _, api, fields, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class PgreSyncBinding(models.Model):
    _name = 'pgre.sync.binding'
    _description = 'PGRE Sync ID Binding'
    _order = 'model, pgre_id'

    model = fields.Char(string='Model', required=True, index=True)
    pgre_id = fields.Integer(string='PGRE ID', required=True, index=True)
    vps_id = fields.Integer(string='VPS ID', index=True)
    source_write_date = fields.Datetime(string='Source Write Date')
    state = fields.Selection([
        ('synced', 'Synced'),
        ('needs_review', 'Needs Review'),
        ('conflict', 'Conflict'),
        ('deleted_source', 'Deleted at Source'),
    ], string='State', default='synced', required=True, index=True)
    last_applied = fields.Datetime(string='Last Applied')
    last_error = fields.Text(string='Last Error')
    note = fields.Char(string='Note')

    _pgre_id_unique = models.Constraint(
        'UNIQUE(model, pgre_id)', 'Binding for this model and PGRE ID already exists.')

    @api.model
    def get_binding(self, model, pgre_id):
        """Return binding record for model+pgre_id or empty recordset."""
        return self.search([('model', '=', model), ('pgre_id', '=', pgre_id)], limit=1)

    @api.model
    def bind(self, model, pgre_id, vps_id, source_write_date):
        """Create or update binding idempotently."""
        binding = self.get_binding(model, pgre_id)
        vals = {
            'model': model,
            'pgre_id': pgre_id,
            'vps_id': vps_id,
            'source_write_date': source_write_date,
            'state': 'synced',
            'last_applied': fields.Datetime.now(),
            'last_error': False,
        }
        if binding:
            binding.write(vals)
        else:
            binding = self.create(vals)
        return binding

    @api.model
    def for_vps(self, model, vps_id):
        """Return binding record for model+vps_id or empty recordset."""
        return self.search([('model', '=', model), ('vps_id', '=', vps_id)], limit=1)