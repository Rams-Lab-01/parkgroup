# -*- coding: utf-8 -*-
"""Wave 4A: negative tests for the constraints migrated off dead
_sql_constraints onto models.Constraint (aml_compliance repo-wide
hardening sweep). Proves each one is now actually enforced by Postgres,
not merely declared.
"""

from odoo.tests.common import TransactionCase


class TestMigratedConstraints(TransactionCase):

    def test_fatf_jurisdiction_country_uniq_rejects_duplicate(self):
        # Seed data (fatf_jurisdiction_data.xml) already ships jurisdiction
        # rows for some countries -- exclude those so the *first* create()
        # here doesn't itself collide with pre-existing data.
        seeded_country_ids = self.env['aml.fatf.jurisdiction'].search([]).country_id.ids
        country = self.env['res.country'].search(
            [('id', 'not in', seeded_country_ids)], limit=1,
        )
        self.env['aml.fatf.jurisdiction'].create({
            'country_id': country.id, 'risk_level': 'grey',
        })
        with self.assertRaises(Exception):
            self.env['aml.fatf.jurisdiction'].create({
                'country_id': country.id, 'risk_level': 'black',
            })

    def test_risk_factor_code_uniq_rejects_duplicate(self):
        self.env['aml.risk.factor'].create({
            'name': 'Test Factor A', 'code': 'WAVE4_DUP_CODE',
        })
        with self.assertRaises(Exception):
            self.env['aml.risk.factor'].create({
                'name': 'Test Factor B', 'code': 'WAVE4_DUP_CODE',
            })

    def test_risk_factor_weight_positive_rejects_negative(self):
        with self.assertRaises(Exception):
            self.env['aml.risk.factor'].create({
                'name': 'Negative Weight Factor',
                'code': 'WAVE4_NEG_WEIGHT',
                'weight': -5.0,
            })

    def test_sanctions_list_name_source_uniq_rejects_duplicate(self):
        self.env['aml.sanctions.list'].create({
            'listed_name': 'Wave4 Test Name', 'list_source': 'un',
        })
        with self.assertRaises(Exception):
            self.env['aml.sanctions.list'].create({
                'listed_name': 'Wave4 Test Name', 'list_source': 'un',
            })
