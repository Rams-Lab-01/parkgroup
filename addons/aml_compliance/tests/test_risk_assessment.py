from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestRiskAssessment(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env.user.write({
            'group_ids': [(4, self.env.ref('aml_compliance.group_aml_manager').id)],
        })
        self.partner = self.env['res.partner'].create({
            'name': 'Test Customer',
            'email': 'test@example.com',
        })

    def _create_assessment(self, **kwargs):
        vals = {
            'partner_id': self.partner.id,
            'assessment_type': 'manual',
        }
        vals.update(kwargs)
        return self.env['aml.risk.assessment'].create(vals)

    def test_compute_risk_score(self):
        """Risk assessment computes a score between 0-100 with correct risk level."""
        assessment = self._create_assessment()
        assessment.action_compute_risk()
        self.assertIn(assessment.state, ('computed',))
        self.assertGreaterEqual(assessment.computed_risk_score, 0.0)
        self.assertLessEqual(assessment.computed_risk_score, 100.0)
        self.assertIn(assessment.computed_risk_level, ['low', 'medium', 'high', 'very_high'])

    def test_review_approve_workflow(self):
        """Full assessment lifecycle: compute → review → approve."""
        assessment = self._create_assessment()
        assessment.action_compute_risk()
        self.assertEqual(assessment.state, 'computed')

        assessment.action_review()
        self.assertEqual(assessment.state, 'reviewed')

        assessment.action_approve()
        self.assertEqual(assessment.state, 'approved')

    def test_requires_edd_for_high_risk(self):
        """High/Very High risk assessments trigger EDD flag."""
        assessment = self._create_assessment()
        assessment.action_compute_risk()
        if assessment.final_risk_level in ('high', 'very_high'):
            self.assertTrue(assessment.requires_edd)
        else:
            self.assertFalse(assessment.requires_edd)
