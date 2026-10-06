from odoo import fields, models

EMIRATES = [
    ('dubai', 'Dubai - Dubai Land Department / RERA'),
    ('abu_dhabi', 'Abu Dhabi - ADREC'),
    ('sharjah', 'Sharjah - Real Estate Registration Department'),
    ('ajman', 'Ajman - Land & Properties Department'),
    ('rak', 'Ras Al Khaimah - Real Estate Regulator'),
    ('fujairah', 'Fujairah - Real Estate Regulator'),
    ('uaq', 'Umm Al Quwain - Real Estate Regulator'),
]


class SgcBrokerDocumentType(models.Model):
    _name = 'sgc.broker.document.type'
    _description = 'Broker Compliance Document Type'
    _order = 'sequence, id'

    _code_unique = models.Constraint('UNIQUE(code)', 'The document code must be unique.')

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    applicant_type = fields.Selection([
        ('both', 'Individual and Company'),
        ('individual', 'Individual broker'),
        ('company', 'Brokerage company'),
    ], required=True, default='both')
    emirate = fields.Selection(
        [('all', 'All emirates')] + EMIRATES, required=True, default='all',
        help='Restrict this requirement to applicants registered with one emirate\'s regulator.')
    required = fields.Boolean(default=True, help='The application cannot be submitted without it.')
    has_expiry = fields.Boolean(string='Has Expiry Date',
                                help='The portal asks for an expiry date and the system alerts before it lapses.')
    is_agreement = fields.Boolean(
        string='Signed Agreement',
        help='This document is the signed brokerage agreement (printable from the portal).')
    description = fields.Text(translate=True, help='Guidance shown to the applicant on the portal.')

    def _applies_to(self, applicant_type, emirate):
        self.ensure_one()
        return (self.applicant_type in ('both', applicant_type)
                and self.emirate in ('all', emirate))
