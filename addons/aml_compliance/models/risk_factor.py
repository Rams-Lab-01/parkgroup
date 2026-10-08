# -*- coding: utf-8 -*-
"""
Configurable Risk Factors

Defines the weighted risk factors used in the automatic risk scoring
engine. Each factor has a category, weight, and scoring logic.
"""

from odoo import api, fields, models, _
import logging

_logger = logging.getLogger(__name__)


class RiskFactor(models.Model):
    """Configurable risk factor used in AML risk scoring"""

    _name = 'aml.risk.factor'
    _description = 'AML Risk Factor'
    _rec_name = 'name'
    _order = 'category, sequence'

    name = fields.Char(string='Factor Name', required=True, translate=True)
    code = fields.Char(
        string='Factor Code', required=True, index=True,
        help='Unique code used by the scoring engine (e.g. GEO_NATIONALITY)',
    )
    category = fields.Selection([
        ('customer', 'Customer'),
        ('geography', 'Geography'),
        ('product', 'Product / Service'),
        ('channel', 'Delivery Channel'),
        ('transaction', 'Transaction'),
    ], string='Category', required=True, default='customer')

    sequence = fields.Integer(default=10)
    weight = fields.Float(
        string='Weight (%)',
        default=10.0,
        help='Relative weight of this factor in overall score calculation',
    )

    max_score = fields.Integer(
        string='Max Score',
        default=100,
        help='Maximum points this factor can contribute',
    )

    active = fields.Boolean(default=True)
    description = fields.Text(string='Description')

    _code_uniq = models.Constraint(
        'unique(code)', 'Risk factor code must be unique.',
    )
    _weight_positive = models.Constraint(
        'CHECK(weight >= 0)', 'Weight must be non-negative.',
    )


class RiskFactorScore(models.Model):
    """Individual factor score within a risk assessment"""

    _name = 'aml.risk.factor.score'
    _description = 'Risk Factor Score'
    _order = 'factor_id'

    assessment_id = fields.Many2one(
        'aml.risk.assessment',
        string='Risk Assessment',
        required=True,
        ondelete='cascade',
        index=True,
    )

    factor_id = fields.Many2one(
        'aml.risk.factor',
        string='Risk Factor',
        required=True,
        ondelete='restrict',
    )

    factor_category = fields.Selection(
        related='factor_id.category',
        store=True,
        string='Category',
    )

    raw_score = fields.Integer(
        string='Raw Score',
        default=0,
        help='Score assigned for this factor (0 to max_score)',
    )

    weighted_score = fields.Float(
        string='Weighted Score',
        compute='_compute_weighted_score',
        store=True,
    )

    justification = fields.Char(
        string='Justification',
        help='Auto-generated explanation for the score',
    )

    @api.depends('raw_score', 'factor_id.weight', 'factor_id.max_score')
    def _compute_weighted_score(self):
        for rec in self:
            if rec.factor_id and rec.factor_id.max_score:
                # Normalize raw score to 0-1 range, then apply weight
                normalized = rec.raw_score / rec.factor_id.max_score
                rec.weighted_score = normalized * rec.factor_id.weight
            else:
                rec.weighted_score = 0.0
