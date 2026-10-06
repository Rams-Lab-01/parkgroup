from odoo import fields, models

from .document_type import EMIRATES


class ResPartner(models.Model):
    _inherit = 'res.partner'

    sgc_is_broker = fields.Boolean(string='Registered Broker', tracking=True)
    sgc_broker_type = fields.Selection([('individual', 'Individual broker'),
                                        ('company', 'Brokerage company')], string='Broker Type')
    sgc_broker_status = fields.Selection([('registered', 'Registered'), ('expired', 'Expired'),
                                          ('suspended', 'Suspended')], string='Broker Status', tracking=True)
    sgc_regulator = fields.Selection(EMIRATES, string='Regulator / Emirate')
    sgc_broker_orn = fields.Char(string='ORN', index=True)
    sgc_broker_brn = fields.Char(string='BRN', index=True)
    sgc_trade_license_no = fields.Char(string='Trade Licence No.', index=True)
    sgc_trade_license_authority = fields.Char(string='Licensing Authority')
    sgc_trade_license_expiry = fields.Date(string='Trade Licence Expiry')
    sgc_regulator_expiry = fields.Date(string='Regulator Registration Expiry')
    sgc_agreement_expiry = fields.Date(string='Brokerage Agreement Expiry', tracking=True)
    sgc_goaml_id = fields.Char(string='goAML ID')
    sgc_emirates_id = fields.Char(string='Emirates ID')
    sgc_passport_no = fields.Char(string='Passport No.')
    sgc_nationality_id = fields.Many2one('res.country', string='Nationality')
    sgc_broker_application_id = fields.Many2one('sgc.broker.application', string='Broker Application',
                                                readonly=True, copy=False)
