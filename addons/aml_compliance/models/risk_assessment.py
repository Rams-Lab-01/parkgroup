# -*- coding: utf-8 -*-
"""
AML Risk Assessment Engine

Core model that computes a composite risk score for a customer
based on FATF jurisdiction, PEP status, source of funds, customer
type, and other configurable risk factors.

Risk Levels (per UAE CBUAE guidance):
  - Low:       0-25    → Simplified CDD
  - Medium:    26-50   → Standard CDD
  - High:      51-75   → Enhanced CDD (EDD)
  - Very High: 76-100  → EDD + MLRO approval required
"""

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, ValidationError
from datetime import timedelta
import logging

_logger = logging.getLogger(__name__)

RISK_THRESHOLDS = {
    'low': (0, 25),
    'medium': (26, 50),
    'high': (51, 75),
    'very_high': (76, 100),
}


class AMLRiskAssessment(models.Model):
    """AML risk assessment linked to a KYC application or partner"""

    _name = 'aml.risk.assessment'
    _description = 'AML Risk Assessment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'assessment_date desc'

    name = fields.Char(
        string='Reference',
        required=True,
        readonly=True,
        default='New',
        copy=False,
        tracking=True,
    )

    # --- Linkage ---
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
    )

    kyc_application_id = fields.Many2one(
        'kyc.application',
        string='KYC Application',
        ondelete='set null',
        index=True,
        help='Source KYC application that triggered this assessment',
    )

    # --- Assessment Metadata ---
    assessment_date = fields.Datetime(
        string='Assessment Date',
        default=fields.Datetime.now,
        tracking=True,
    )

    assessment_type = fields.Selection([
        ('initial', 'Initial Assessment'),
        ('periodic', 'Periodic Review'),
        ('trigger', 'Trigger Event'),
        ('manual', 'Manual Assessment'),
    ], string='Assessment Type', default='initial', required=True, tracking=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('computed', 'Computed'),
        ('reviewed', 'Reviewed'),
        ('approved', 'Approved'),
        ('overridden', 'Overridden'),
    ], string='Status', default='draft', tracking=True, index=True)

    # --- Computed Risk Score ---
    computed_risk_score = fields.Float(
        string='Computed Risk Score',
        digits=(5, 2),
        readonly=True,
        tracking=True,
        help='Auto-calculated risk score from 0 to 100',
    )

    computed_risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('very_high', 'Very High'),
    ], string='Computed Risk Level', readonly=True, tracking=True)

    # --- Final Risk (may differ if overridden) ---
    final_risk_level = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('very_high', 'Very High'),
    ], string='Final Risk Level', tracking=True,
       help='Final risk level after review. May differ from computed if overridden.')

    is_overridden = fields.Boolean(
        string='Manually Overridden',
        default=False,
        tracking=True,
    )

    override_reason = fields.Text(
        string='Override Justification',
        tracking=True,
    )

    override_user_id = fields.Many2one(
        'res.users',
        string='Overridden By',
        readonly=True,
    )

    override_date = fields.Datetime(
        string='Override Date',
        readonly=True,
    )

    # --- Factor Scores (detail lines) ---
    factor_score_ids = fields.One2many(
        'aml.risk.factor.score',
        'assessment_id',
        string='Factor Scores',
    )

    # --- EDD Trigger ---
    requires_edd = fields.Boolean(
        string='Requires Enhanced Due Diligence',
        compute='_compute_requires_edd',
        store=True,
    )

    edd_reason = fields.Text(
        string='EDD Trigger Reason',
        readonly=True,
    )

    # --- Review Fields ---
    reviewer_id = fields.Many2one(
        'res.users',
        string='Reviewed By',
        tracking=True,
    )

    review_date = fields.Datetime(
        string='Review Date',
    )

    review_notes = fields.Text(
        string='Review Notes',
    )

    approved_by_id = fields.Many2one(
        'res.users',
        string='Approved By',
        tracking=True,
    )

    approval_date = fields.Datetime(
        string='Approval Date',
    )

    # --- Scheduling ---
    next_review_date = fields.Date(
        string='Next Review Date',
        compute='_compute_next_review_date',
        store=True,
        tracking=True,
    )

    # --- Individual Factor Inputs (for quick view) ---
    nationality_risk = fields.Char(
        string='Nationality Risk',
        readonly=True,
        help='FATF classification of customer nationality',
    )

    pep_status = fields.Boolean(
        string='PEP Status',
        readonly=True,
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )

    goaml_report_count = fields.Integer(
        string='# goAML Reports',
        compute='_compute_goaml_report_count',
    )

    # -------------------------------------------------------
    # COMPUTED FIELDS
    # -------------------------------------------------------

    @api.depends('final_risk_level')
    def _compute_requires_edd(self):
        for rec in self:
            rec.requires_edd = rec.final_risk_level in ('high', 'very_high')

    @api.depends('final_risk_level', 'assessment_date')
    def _compute_next_review_date(self):
        """Review frequency per CBUAE AML guidance:
        Low: 36 months, Medium: 24 months, High: 12 months, Very High: 6 months
        """
        review_months = {
            'low': 36,
            'medium': 24,
            'high': 12,
            'very_high': 6,
        }
        for rec in self:
            if rec.assessment_date and rec.final_risk_level:
                months = review_months.get(rec.final_risk_level, 24)
                rec.next_review_date = (
                    rec.assessment_date + timedelta(days=months * 30)
                ).date()
            else:
                rec.next_review_date = False

    def _compute_goaml_report_count(self):
        for rec in self:
            rec.goaml_report_count = self.env['aml.goaml.report'].search_count([
                ('risk_assessment_id', '=', rec.id),
            ])

    def action_view_goaml_reports(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('goAML Reports'),
            'res_model': 'aml.goaml.report',
            'view_mode': 'list,form',
            'domain': [('risk_assessment_id', '=', self.id)],
            'context': {'default_risk_assessment_id': self.id},
        }

    # -------------------------------------------------------
    # CRUD OVERRIDES
    # -------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'aml.risk.assessment'
                ) or 'New'
        return super().create(vals_list)

    # -------------------------------------------------------
    # RISK SCORING ENGINE
    # -------------------------------------------------------

    def action_compute_risk(self):
        """Main risk scoring engine. Evaluates all active risk factors
        and computes a composite weighted score."""
        for rec in self:
            partner = rec.partner_id
            kyc = rec.kyc_application_id
            factor_scores = []
            edd_reasons = []

            # Fetch all active risk factors
            factors = self.env['aml.risk.factor'].search([('active', '=', True)])

            for factor in factors:
                raw_score = 0
                justification = ''

                if factor.code == 'GEO_NATIONALITY':
                    raw_score, justification = rec._score_nationality(partner)

                elif factor.code == 'GEO_RESIDENCE':
                    raw_score, justification = rec._score_residence(partner)

                elif factor.code == 'CUST_PEP':
                    raw_score, justification = rec._score_pep(partner, kyc)

                elif factor.code == 'CUST_TYPE':
                    raw_score, justification = rec._score_customer_type(partner)

                elif factor.code == 'CUST_SOURCE_FUNDS':
                    raw_score, justification = rec._score_source_of_funds(partner, kyc)

                elif factor.code == 'CUST_SOURCE_WEALTH':
                    raw_score, justification = rec._score_source_of_wealth(partner, kyc)

                elif factor.code == 'CUST_INCOME_LEVEL':
                    raw_score, justification = rec._score_income_level(partner)

                elif factor.code == 'PROD_REAL_ESTATE':
                    raw_score, justification = rec._score_product_realestate(partner)

                elif factor.code == 'CHAN_NON_FACE':
                    raw_score, justification = rec._score_channel(partner, kyc)

                elif factor.code == 'TXN_VALUE':
                    raw_score, justification = rec._score_transaction_value(partner)

                else:
                    # Unknown factor — skip silently
                    continue

                # Cap raw_score at max_score
                raw_score = min(raw_score, factor.max_score)

                factor_scores.append(Command.create({
                    'factor_id': factor.id,
                    'raw_score': raw_score,
                    'justification': justification,
                }))

                # Track EDD triggers
                if raw_score >= factor.max_score * 0.75:
                    edd_reasons.append(f"{factor.name}: {justification}")

            # Write factor scores
            rec.factor_score_ids.unlink()
            rec.write({
                'factor_score_ids': factor_scores,
            })

            # Compute composite score (sum of weighted scores)
            total_weighted = sum(rec.factor_score_ids.mapped('weighted_score'))
            # Clamp to 0-100
            total_weighted = max(0.0, min(100.0, total_weighted))

            # Determine risk level from score
            risk_level = 'low'
            for level, (low, high) in RISK_THRESHOLDS.items():
                if low <= total_weighted <= high:
                    risk_level = level
                    break

            # Record nationality risk for quick reference
            fatf_class = self.env['aml.fatf.jurisdiction'].is_high_risk_country(
                partner.country_id.id if partner.country_id else False
            )

            rec.write({
                'computed_risk_score': total_weighted,
                'computed_risk_level': risk_level,
                'final_risk_level': risk_level if not rec.is_overridden else rec.final_risk_level,
                'nationality_risk': fatf_class or _('Standard'),
                'pep_status': partner.x_is_pep if hasattr(partner, 'x_is_pep') else False,
                'edd_reason': '\n'.join(edd_reasons) if edd_reasons else False,
                'state': 'computed',
            })

            _logger.info(
                'Risk assessment %s computed: score=%.2f, level=%s for partner %s',
                rec.name, total_weighted, risk_level, partner.display_name,
            )

    # -------------------------------------------------------
    # INDIVIDUAL FACTOR SCORING METHODS
    # -------------------------------------------------------

    def _score_nationality(self, partner):
        """Score based on customer nationality vs FATF lists"""
        nationality = partner.x_nationality_id if hasattr(partner, 'x_nationality_id') and partner.x_nationality_id else partner.country_id
        if not nationality:
            return 50, _('No nationality on file — treated as medium risk')

        score = self.env['aml.fatf.jurisdiction'].get_risk_score_for_country(nationality.id)
        if score > 0:
            fatf = self.env['aml.fatf.jurisdiction'].is_high_risk_country(nationality.id)
            label = dict(self.env['aml.fatf.jurisdiction']._fields['risk_level'].selection).get(fatf, fatf)
            return score, _('FATF %s: %s', label, nationality.name)
        return 0, _('Standard jurisdiction: %s', nationality.name)

    def _score_residence(self, partner):
        """Score based on country of residence"""
        country = partner.country_id
        if not country:
            return 30, _('No country of residence specified')
        score = self.env['aml.fatf.jurisdiction'].get_risk_score_for_country(country.id)
        if score > 0:
            return score, _('Resident in FATF-listed country: %s', country.name)
        return 0, _('Standard residence: %s', country.name)

    def _score_pep(self, partner, kyc):
        """Politically Exposed Person — automatic high score"""
        is_pep = False
        if hasattr(partner, 'x_is_pep') and partner.x_is_pep:
            is_pep = True
        elif kyc and hasattr(kyc, 'is_pep') and kyc.is_pep:
            is_pep = True

        if is_pep:
            return 100, _('Customer identified as PEP')
        return 0, _('Not a PEP')

    def _score_customer_type(self, partner):
        """Score based on customer type (company vs individual)"""
        if partner.is_company:
            # Companies have inherently higher risk due to beneficial ownership complexity
            return 40, _('Legal entity — beneficial ownership verification required')
        return 10, _('Natural person')

    def _score_source_of_funds(self, partner, kyc):
        """Score based on source of funds complexity"""
        sof_count = 0
        if hasattr(partner, 'x_source_of_funds') and partner.x_source_of_funds:
            sof_count = len(partner.x_source_of_funds)
        elif kyc and hasattr(kyc, 'source_of_funds_id') and kyc.source_of_funds_id:
            # The portal captures a single primary source of funds.
            sof_count = 1

        if sof_count == 0:
            return 70, _('No source of funds declared — high risk')
        elif sof_count >= 3:
            return 40, _('Multiple sources of funds (%d) — complex structure', sof_count)
        return 10, _('Source of funds declared (%d source(s))', sof_count)

    def _score_source_of_wealth(self, partner, kyc):
        """Score based on source of wealth declaration"""
        sow_count = 0
        if hasattr(partner, 'x_source_of_wealth') and partner.x_source_of_wealth:
            sow_count = len(partner.x_source_of_wealth)
        elif kyc and hasattr(kyc, 'source_of_wealth_id') and kyc.source_of_wealth_id:
            # The portal captures a single primary source of wealth.
            sow_count = 1

        if sow_count == 0:
            return 50, _('No source of wealth declared')
        return 5, _('Source of wealth declared (%d source(s))', sow_count)

    def _score_income_level(self, partner):
        """Score based on annual income level (high income = higher risk for AML)"""
        income = 0
        if hasattr(partner, 'x_annual_income') and partner.x_annual_income:
            try:
                income = float(partner.x_annual_income)
            except (ValueError, TypeError):
                income = 0

        if income == 0:
            return 40, _('Annual income not declared')
        elif income > 1000000:
            return 60, _('High income declared: %s', income)
        elif income > 500000:
            return 30, _('Medium-high income: %s', income)
        return 10, _('Standard income level: %s', income)

    def _score_product_realestate(self, partner):
        """Real estate is inherently higher risk per FATF/CBUAE guidance"""
        # In a real estate company, all customers get elevated product risk
        return 60, _('Real estate sector — high-risk product category per FATF')

    def _score_channel(self, partner, kyc):
        """Non-face-to-face channels carry higher risk"""
        if kyc and hasattr(kyc, 'create_uid') and kyc.create_uid:
            # Portal-submitted KYC = non-face-to-face
            portal_group = self.env.ref('base.group_portal', raise_if_not_found=False)
            if portal_group and kyc.create_uid.has_group('base.group_portal'):
                return 50, _('KYC submitted via online portal (non-face-to-face)')
        return 10, _('Face-to-face verification')

    def _score_transaction_value(self, partner):
        """Score based on historical transaction volume with this customer"""
        if not partner:
            return 0, _('No partner')
        # Sum of all posted invoices for this partner
        invoices = self.env['account.move'].sudo().search([
            ('partner_id', '=', partner.id),
            ('move_type', 'in', ('out_invoice', 'out_refund')),
            ('state', '=', 'posted'),
        ])
        total = sum(invoices.mapped('amount_total_signed'))

        if total > 5000000:  # AED 5M+
            return 90, _('Very high transaction volume: AED %.2f', total)
        elif total > 1000000:  # AED 1M+
            return 60, _('High transaction volume: AED %.2f', total)
        elif total > 100000:  # AED 100K+
            return 30, _('Medium transaction volume: AED %.2f', total)
        return 10, _('Low transaction volume: AED %.2f', total)

    # -------------------------------------------------------
    # WORKFLOW ACTIONS
    # -------------------------------------------------------

    def action_review(self):
        """Mark assessment as reviewed by compliance officer"""
        for rec in self:
            if rec.state not in ('computed', 'overridden'):
                raise UserError(_('Only computed or overridden assessments can be reviewed.'))
            rec.write({
                'state': 'reviewed',
                'reviewer_id': self.env.uid,
                'review_date': fields.Datetime.now(),
            })

    def action_approve(self):
        """MLRO approval — required for high/very_high risk"""
        is_manager = self.env.user.has_group('aml_compliance.group_aml_manager')
        is_mlro = self.env.user.has_group('aml_compliance.group_mlro')
        if not (is_manager or is_mlro):
            raise UserError(_('Only AML Manager or MLRO can approve risk assessments.'))

        for rec in self:
            if rec.state != 'reviewed':
                raise UserError(_('Assessment must be reviewed before approval.'))
            if rec.final_risk_level == 'very_high' and not is_mlro:
                raise UserError(_('Very High risk assessments require MLRO approval.'))
            rec.write({
                'state': 'approved',
                'approved_by_id': self.env.uid,
                'approval_date': fields.Datetime.now(),
            })
            # Update partner risk level
            rec.partner_id.write({
                'aml_risk_level': rec.final_risk_level,
                'aml_last_assessment_date': rec.assessment_date,
                'aml_next_review_date': rec.next_review_date,
            })

    def action_reset_draft(self):
        """Reset to draft for re-assessment"""
        for rec in self:
            rec.write({
                'state': 'draft',
                'computed_risk_score': 0,
                'computed_risk_level': False,
            })

    def action_open_override_wizard(self):
        """Open wizard to override computed risk level"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Override Risk Level'),
            'res_model': 'aml.risk.override.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_assessment_id': self.id,
                'default_current_risk_level': self.computed_risk_level,
            },
        }

    # -------------------------------------------------------
    # PHASE 6: PERIODIC REVIEW SCHEDULER
    # -------------------------------------------------------

    @api.model
    def run_periodic_review_check(self):
        """Scheduled action: check for assessments due for periodic review.
        Creates activities for the AML manager when reviews are due/overdue.
        """
        _logger.info('AML Periodic Review Check: starting...')
        today = fields.Date.today()

        # Find approved assessments with next_review_date <= today
        overdue = self.search([
            ('state', '=', 'approved'),
            ('next_review_date', '<=', today),
        ])

        aml_manager_group = self.env.ref(
            'aml_compliance.group_aml_manager', raise_if_not_found=False
        )
        if not aml_manager_group:
            _logger.warning('AML Manager group not found.')
            return

        # Get first AML manager as activity assignee
        manager = aml_manager_group.users[:1]

        review_count = 0
        for assessment in overdue:
            # Check if we already have an open activity for this
            existing_activity = self.env['mail.activity'].search([
                ('res_model', '=', 'aml.risk.assessment'),
                ('res_id', '=', assessment.id),
                ('summary', 'like', 'Periodic AML Review Due'),
            ], limit=1)
            if existing_activity:
                continue

            assessment.activity_schedule(
                'mail.mail_activity_data_todo',
                user_id=manager.id if manager else self.env.uid,
                summary=_('Periodic AML Review Due — %s', assessment.partner_id.name),
                note=_(
                    'Risk assessment %s for %s is due for periodic review. '
                    'Current risk level: %s. Last assessment: %s.',
                    assessment.name,
                    assessment.partner_id.name,
                    assessment.final_risk_level,
                    assessment.assessment_date,
                ),
                date_deadline=today,
            )
            review_count += 1

        _logger.info(
            'AML Periodic Review: %d review reminders created (%d overdue total).',
            review_count, len(overdue),
        )
        return review_count

    @api.model
    def run_document_expiry_check(self):
        """Scheduled action: check for expiring KYC documents.
        Looks at KYC applications with expiry dates approaching.
        """
        _logger.info('AML Document Expiry Check: starting...')
        today = fields.Date.today()
        warning_date = today + timedelta(days=30)  # 30-day warning

        # Check if kyc_management has expiry fields
        KycApp = self.env.get('kyc.application')
        if KycApp is None:
            _logger.info('kyc.application model not available.')
            return 0

        # Search for KYC applications with partners that have upcoming review
        partners_needing_review = self.env['res.partner'].search([
            ('aml_next_review_date', '<=', warning_date),
            ('aml_next_review_date', '>', today),
            ('aml_risk_level', '!=', False),
        ])

        count = 0
        for partner in partners_needing_review:
            # Schedule activity on partner
            existing = self.env['mail.activity'].search([
                ('res_model', '=', 'res.partner'),
                ('res_id', '=', partner.id),
                ('summary', 'like', 'AML Review Approaching'),
            ], limit=1)
            if existing:
                continue

            partner.activity_schedule(
                'mail.mail_activity_data_todo',
                summary=_('AML Review Approaching — %s', partner.name),
                note=_(
                    'Partner %s has an AML review date of %s. '
                    'Please schedule a periodic risk re-assessment.',
                    partner.name,
                    partner.aml_next_review_date,
                ),
                date_deadline=partner.aml_next_review_date,
            )
            count += 1

        _logger.info('AML Document Expiry: %d upcoming review warnings created.', count)
        return count
