import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Cap payload to ~4000 chars to avoid bloating the log
PAYLOAD_CAP = 4000


def _cap(text):
    """Truncate text to PAYLOAD_CAP chars with ellipsis."""
    if not text:
        return text
    text = str(text)
    if len(text) <= PAYLOAD_CAP:
        return text
    return text[:PAYLOAD_CAP - 3] + '...'


class PgreSyncLog(models.Model):
    _name = 'pgre.sync.log'
    _description = 'PGRE Sync Operation Log'
    _order = 'ts desc, id desc'
    _rec_name = 'summary'

    ts = fields.Datetime(string='Timestamp', default=fields.Datetime.now, required=True, index=True)
    model = fields.Char(string='Model', index=True)
    pgre_id = fields.Integer(string='PGRE ID', index=True)
    vps_id = fields.Integer(string='VPS ID', index=True)
    action = fields.Selection([
        ('create', 'Created'),
        ('write', 'Updated'),
        ('post', 'Posted'),
        ('delete', 'Deleted'),
        ('skip', 'Skipped'),
        ('conflict', 'Conflict'),
        ('error', 'Error'),
        ('info', 'Info'),
    ], string='Action', required=True, index=True)
    dry_run = fields.Boolean(string='Dry Run', default=False, index=True)
    summary = fields.Text(string='Summary')
    payload = fields.Text(string='Payload (JSON)')

    @api.model
    def log(self, model, pgre_id, vps_id, action, dry_run, summary, payload=None):
        """Create a log entry. payload is JSON-serialized and capped."""
        vals = {
            'model': model,
            'pgre_id': pgre_id,
            'vps_id': vps_id,
            'action': action,
            'dry_run': dry_run,
            'summary': summary,
        }
        if payload is not None:
            vals['payload'] = _cap(json.dumps(payload, default=str, ensure_ascii=False))
        return self.create(vals)

    @api.model
    def log_error(self, model, pgre_id, vps_id, dry_run, summary, error, traceback_tail=None):
        """Convenience method for error logging."""
        payload = {'error': str(error)}
        if traceback_tail:
            payload['traceback'] = traceback_tail
        return self.log(model, pgre_id, vps_id, 'error', dry_run, summary, payload)

    @api.model
    def log_info(self, model, pgre_id, vps_id, dry_run, summary, payload=None):
        """Convenience method for info logging."""
        return self.log(model, pgre_id, vps_id, 'info', dry_run, summary, payload)