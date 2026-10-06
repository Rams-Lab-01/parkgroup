import base64
import posixpath
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

ALLOWED_EXTENSIONS = {'pdf': (b'%PDF',), 'jpg': (b'\xff\xd8\xff',), 'jpeg': (b'\xff\xd8\xff',),
                      'png': (b'\x89PNG\r\n\x1a\n',)}
MAX_UPLOAD_MB_PARAM = 'sgc_broker.max_upload_mb'
DEFAULT_MAX_MB = 10
MAX_DOCS_PER_APPLICATION = 40
MAX_DOCS_PER_TYPE = 5


class SgcBrokerApplicationDocument(models.Model):
    _name = 'sgc.broker.application.document'
    _description = 'Broker Application Document'
    _order = 'type_id, id'

    application_id = fields.Many2one('sgc.broker.application', required=True, ondelete='cascade', index=True)
    type_id = fields.Many2one('sgc.broker.document.type', required=True, ondelete='restrict')
    file = fields.Binary(string='File', attachment=True, required=True)
    filename = fields.Char(required=True)
    issue_date = fields.Date()
    expiry_date = fields.Date()
    state = fields.Selection([
        ('pending', 'Pending review'),
        ('accepted', 'Accepted'),
        ('rejected', 'Rejected'),
    ], default='pending', required=True)
    remarks = fields.Char(string='Reviewer remarks')
    has_expiry = fields.Boolean(related='type_id.has_expiry')

    @api.model
    def _max_bytes(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(MAX_UPLOAD_MB_PARAM)
        try:
            mb = int(raw) if raw else DEFAULT_MAX_MB
        except ValueError:
            mb = DEFAULT_MAX_MB
        return max(mb, 1) * 1024 * 1024

    @api.model
    def _validate_upload(self, filename, raw_bytes):
        """Allow only PDF / JPG / PNG whose real content matches the extension."""
        ext = (filename or '').rsplit('.', 1)[-1].lower() if '.' in (filename or '') else ''
        if ext not in ALLOWED_EXTENSIONS:
            raise ValidationError(_('Only PDF, JPG or PNG files are accepted.'))
        if not raw_bytes:
            raise ValidationError(_('The uploaded file is empty.'))
        if len(raw_bytes) > self._max_bytes():
            raise ValidationError(_('The file is too large (maximum %s MB).', self._max_bytes() // (1024 * 1024)))
        if not any(raw_bytes.startswith(sig) for sig in ALLOWED_EXTENSIONS[ext]):
            raise ValidationError(_('The file content does not match its type. Upload a genuine PDF, JPG or PNG.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('filename'):
                # keep only a safe base name: no path components, control characters or odd lengths
                name = posixpath.basename(vals['filename'].replace('\\', '/'))
                name = re.sub(r'[\x00-\x1f\x7f<>:"|?*]', '', name)
                stem, dot, ext = name.rpartition('.')
                if dot and len(name) > 150:
                    name = stem[:max(150 - len(ext) - 1, 1)] + '.' + ext     # shorten the name, keep the extension
                vals['filename'] = name[:150] or 'document'
            self._validate_upload(vals.get('filename'), base64.b64decode(vals.get('file') or b''))
            app_id, type_id = vals.get('application_id'), vals.get('type_id')
            if app_id:
                self.env['sgc.broker.application'].browse(app_id)._lock_row()   # serialise concurrent uploads
                existing = self.sudo().search([('application_id', '=', app_id)])
                if len(existing) >= MAX_DOCS_PER_APPLICATION:
                    raise ValidationError(_('Too many documents on this application (maximum %s).',
                                            MAX_DOCS_PER_APPLICATION))
                if len(existing.filtered(lambda d: d.type_id.id == type_id)) >= MAX_DOCS_PER_TYPE:
                    raise ValidationError(_('Too many files for this document type (maximum %s). '
                                            'Remove one first.', MAX_DOCS_PER_TYPE))
        return super().create(vals_list)

    @api.constrains('issue_date', 'expiry_date')
    def _check_dates(self):
        for rec in self:
            if rec.issue_date and rec.expiry_date and rec.expiry_date < rec.issue_date:
                raise ValidationError(_('The expiry date cannot be before the issue date.'))

    def action_accept(self):
        self.write({'state': 'accepted', 'remarks': False})

    def action_reject(self):
        self.write({'state': 'rejected'})
