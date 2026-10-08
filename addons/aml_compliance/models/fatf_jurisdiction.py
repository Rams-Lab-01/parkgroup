# -*- coding: utf-8 -*-
"""
FATF Jurisdiction Classification

Maintains the FATF high-risk and increased monitoring jurisdiction lists.
Updated per FATF plenary outcomes (typically Feb/Jun/Oct each year).

References:
- FATF High-Risk Jurisdictions subject to a Call for Action (Black List)
- FATF Jurisdictions under Increased Monitoring (Grey List)
"""

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class FATFJurisdiction(models.Model):
    """FATF jurisdiction risk classification linked to res.country"""

    _name = 'aml.fatf.jurisdiction'
    _description = 'FATF Jurisdiction Classification'
    _rec_name = 'country_id'
    _order = 'risk_level desc, country_id'

    country_id = fields.Many2one(
        'res.country',
        string='Country',
        required=True,
        ondelete='cascade',
        index=True,
    )
    risk_level = fields.Selection([
        ('black', 'High-Risk (Black List)'),
        ('grey', 'Increased Monitoring (Grey List)'),
        ('elevated', 'Elevated Risk'),
    ], string='FATF Classification', required=True, default='grey')

    risk_score = fields.Integer(
        string='Risk Score Contribution',
        default=30,
        help='Points added to overall risk score when customer holds this nationality',
    )

    date_listed = fields.Date(
        string='Date Listed',
        default=fields.Date.today,
        help='When this country was added to the FATF list',
    )

    date_delisted = fields.Date(
        string='Date Delisted',
        help='When this country was removed (leave empty if still listed)',
    )

    active = fields.Boolean(default=True)

    notes = fields.Text(
        string='Notes',
        help='Reason for listing, deficiencies identified by FATF',
    )

    _country_uniq = models.Constraint(
        'unique(country_id)',
        'Each country can only appear once in the FATF jurisdiction list.',
    )

    @api.model
    def is_high_risk_country(self, country_id):
        """Check if a country is on FATF high-risk or grey list.
        Returns the risk classification or False.
        """
        if not country_id:
            return False
        rec = self.search([
            ('country_id', '=', country_id),
            ('active', '=', True),
            ('date_delisted', '=', False),
        ], limit=1)
        return rec.risk_level if rec else False

    @api.model
    def get_risk_score_for_country(self, country_id):
        """Return risk score contribution for a country. 0 if not listed."""
        if not country_id:
            return 0
        rec = self.search([
            ('country_id', '=', country_id),
            ('active', '=', True),
            ('date_delisted', '=', False),
        ], limit=1)
        return rec.risk_score if rec else 0
