import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class PgreSyncCursor(models.Model):
    _name = 'pgre.sync.cursor'
    _description = 'PGRE Sync Per-Model Cursor'
    _order = 'model'

    model = fields.Char(string='Model', required=True, index=True)
    last_write_date = fields.Datetime(string='Last Source Write Date', index=True)
    last_run = fields.Datetime(string='Last Run')
    last_result = fields.Text(string='Last Run Result')

    _model_unique = models.Constraint(
        'UNIQUE(model)', 'Cursor for this model already exists.')

    @api.model
    def get_cursor(self, model):
        """Get or create cursor for model."""
        cursor = self.search([('model', '=', model)], limit=1)
        if not cursor:
            cursor = self.create({'model': model})
        return cursor