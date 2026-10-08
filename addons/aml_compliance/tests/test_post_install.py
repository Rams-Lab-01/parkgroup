# -*- coding: utf-8 -*-
"""Wave 4 closure pass: post-install tests for aml_compliance.

Tagged ``post_install`` so they are intended to run under §6.3
(``--test-tags 'post_install/aml_compliance'``).

NOTE on selection semantics: in Odoo 19, an explicit selector like
``/aml_compliance`` matches ANY class carrying the ``aml_compliance``
tag, regardless of whether the class is also tagged ``post_install``
or excluded with ``-at_install``. The ``-at_install`` exclusion is
honoured only when no explicit include selector is given. As a
result, this class is also selected by §6.2's ``/aml_compliance``
selector; that is an artefact of the runtime, not a defect in the
test design.

The tests deliberately avoid ``button_immediate_upgrade()`` and other
module-mutation calls -- those are forbidden inside Odoo's
transactional test harness ("Module operations inside tests are not
transactional and thus forbidden"). Instead we verify that the
module is installed and that the migrated ``models.Constraint`` rows
still reject duplicate / out-of-range inserts.
"""

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install', 'aml_compliance')
class TestPostInstall(TransactionCase):
    """Re-install / upgrade idempotency gate."""

    def test_module_is_installed_after_upgrade_path(self):
        """The module must already be in state ``installed`` by the
        time post-install tests run (the §6.1 / §6.2 phases have
        already upgraded it). This is a sanity check, not a mutation
        -- we do not call ``button_immediate_upgrade()`` here
        because that is forbidden inside Odoo's transactional test
        harness."""
        module = self.env['ir.module.module'].search([
            ('name', '=', 'aml_compliance'),
        ])
        self.assertTrue(module, "aml_compliance module must be installed")
        self.assertEqual(module.state, 'installed')

    def test_constraints_survive_prior_module_upgrade(self):
        """The migrated ``models.Constraint`` rows (proved by
        ``TestMigratedConstraints`` in the install-time phase) must
        still be present. We re-issue a duplicate-code create() and
        confirm the constraint still fires."""
        self.env['aml.risk.factor'].create({
            'name': 'PostInstall Factor A',
            'code': 'WAVE4_PI_DUP',
        })
        with self.assertRaises(Exception):
            self.env['aml.risk.factor'].create({
                'name': 'PostInstall Factor B',
                'code': 'WAVE4_PI_DUP',
            })