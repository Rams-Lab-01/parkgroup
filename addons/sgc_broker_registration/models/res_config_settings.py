from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    sgc_broker_agreement_validity_months = fields.Integer(
        string='Agreement validity (months)', config_parameter='sgc_broker.agreement_validity_months',
        default=12, help='Counted from the approval date (and from the old expiry on renewal).')
    sgc_broker_expiry_pre_days = fields.Integer(
        string='Reminder before expiry (days)', config_parameter='sgc_broker.expiry_pre_days', default=5)
    sgc_broker_expiry_repeat_days = fields.Integer(
        string='Reminder repeat after expiry (days)', config_parameter='sgc_broker.expiry_repeat_days',
        default=15)
    sgc_broker_extra_notify_emails = fields.Char(
        string='Extra reminder recipients', config_parameter='sgc_broker.extra_notify_emails',
        help='Comma-separated emails (for example compliance@company.com) copied on every expiry email.')
    sgc_broker_max_upload_mb = fields.Integer(
        string='Maximum upload size (MB)', config_parameter='sgc_broker.max_upload_mb', default=10)
    sgc_broker_max_registrations_per_ip_hour = fields.Integer(
        string='Max registrations per IP per hour', config_parameter='sgc_broker.max_registrations_per_ip_hour',
        default=10, help='Anti-abuse limit. Behind a reverse proxy Odoo must run with proxy_mode, '
                         'otherwise every visitor shares the proxy address.')
