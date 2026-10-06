from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sgc_pdc_upcoming_days = fields.Integer(
        string='Upcoming alert (days before maturity)',
        config_parameter='sgc_pdc.upcoming_days', default=7)
    sgc_pdc_extra_notify_emails = fields.Char(
        string='Extra alert recipients',
        config_parameter='sgc_pdc.extra_notify_emails',
        help='Comma-separated email addresses that also receive upcoming / matured cheque emails '
             '(for example accounts@company.com).')
