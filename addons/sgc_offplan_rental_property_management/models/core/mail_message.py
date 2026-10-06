"""mail.message Python extension for the audit trail (design §10, [C12]).

Extends the shared mail.message model in Python instead of a new addon or a
data-tracked XML field: a sanitized chatter entry that backs an audit event can
link back to it. ondelete='set null' keeps event rows immutable even when the
message is removed (P0-3).
"""

from odoo import fields, models


class MailMessage(models.Model):
    _inherit = 'mail.message'

    sgc_audit_event_id = fields.Many2one(
        'sgc.critical.audit.event',
        string='Linked Audit Event',
        index=True,
        ondelete='set null')