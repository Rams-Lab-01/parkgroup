# -*- coding: utf-8 -*-
# Copyright (C) 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

"""Aggregate report data providers.

The Critical Audit chain-verification report is an *aggregate* report: it is
opened from the app menu with no active records, so ``docids`` is empty.  With
no report model registered, Odoo's generic rendering context browses
``report.model`` with an empty id list and the template's ``docs`` loop runs
zero times, producing a blank (1 KB) PDF.

Registering a model named ``report.<report_name>`` (see
``ir.actions.report._get_rendering_context_model``) lets ``_get_report_values``
supply the whole-company context the template renders from.

Note on ``_table``: ``_name`` here is 84 characters, and
``models.AbstractModel`` derives ``_table`` from ``_name``.  ``add_to_registry``
calls ``check_pg_name(model_cls._table)`` unconditionally -- including for
``_auto = False`` models -- so the derived name trips PostgreSQL's 63-character
identifier limit and aborts the registry load.  ``_table`` is therefore set
explicitly to a short, stable value (no physical table is created because
AbstractModel keeps ``_auto = False``).
"""

from odoo import api, models

from odoo.addons.sgc_offplan_rental_property_management.models.core.critical_audit_chain \
    import ATTESTABLE_EPOCH_CHAIN_NO, EXPECTED_UNATTESTABLE

# Models excluded from the coverage denominator.  Abstract models and the mixin
# are excluded by type; the verification verdict log is excluded by name because
# it is audit infrastructure, not a business subject: the verifier's own log must
# not be counted as an unobserved model.  Excluding it also keeps the disclosed
# denominator stable at 71 when the model is added.
_COVERAGE_EXCLUDED = frozenset({
    'sgc.critical.audit.verdict',
})


class CriticalAuditVerificationReport(models.AbstractModel):
    _name = ('report.sgc_offplan_rental_property_management.'
             'report_critical_audit_verification_document')
    _table = 'sgc_audit_chain_verify_rep'
    _description = 'Critical Audit Chain Verification Report (aggregate)'

    @api.model
    def _get_report_values(self, docids, data=None):
        company = self.env.company
        _tenant_id, tenant_uuid = self.env['sgc.critical.audit.tenant']._ensure_tenant(self.env)
        events = self.env['sgc.critical.audit.event'].sudo().search(
            [
                ('tenant_uuid', '=', tenant_uuid),
                ('company_id', '=', company.id),
            ],
            order='chain_no asc, id asc',
        )
        verification = self.env['sgc.critical.audit.chain'].verify_chain(
            self.env, tenant_uuid, company.id,
        )
        last_verdict = self.env['sgc.critical.audit.verdict'].sudo().search(
            [('tenant_uuid', '=', tenant_uuid), ('company_id', '=', company.id)],
            order='run_at desc, id desc', limit=1,
        )
        return {
            'doc_ids': [],
            'doc_model': 'sgc.critical.audit.event',
            'docs': [],
            'company': company,
            'tenant_uuid': tenant_uuid,
            'all_events': events,
            'verification': verification,
            'coverage': self._capture_coverage(),
            'epoch_chain_no': ATTESTABLE_EPOCH_CHAIN_NO,
            'expected_unattestable': EXPECTED_UNATTESTABLE,
            'last_verdict': last_verdict,
        }

    @api.model
    def _capture_coverage(self):
        """How much of this module the chain actually observes.

        The capture hook lives on ``sgc.critical.audit.mixin``, so a model that
        does not inherit it emits no event and the verifier - which re-hashes
        stored events - cannot see a change to it.  A verification report that
        does not say so invites the reader to read "chain verified" as
        estate-wide.

        Counts concrete (non-abstract) models registered under this module, which
        includes the core models this module only extends, so the gap is never
        understated.  The mixin, abstract report models and the audit verdict log
        are excluded.
        """
        mixin = 'sgc.critical.audit.mixin'
        registered = [
            model for model in self.env.registry.values()
            if getattr(model, '_module', None) == 'sgc_offplan_rental_property_management'
            and not getattr(model, '_abstract', False)
            and getattr(model, '_name', None) not in _COVERAGE_EXCLUDED
        ]
        wired = [
            model for model in registered
            if mixin in [getattr(cls, '_name', None) for cls in model.__mro__]
        ]
        detail = []
        for model in sorted(wired, key=lambda m: m._name):
            watched = getattr(model, '_audit_watched_fields', None)
            detail.append({
                'model': model._name,
                'scope': 'all' if watched is None else 'allowlist',
                'fields': [] if watched is None else sorted(watched),
                'unlink_gated': bool(getattr(
                    model, '_audit_unlink_requires_reason', True)),
            })
        return {
            'wired': len(wired),
            'total': len(registered),
            'gap': len(registered) - len(wired),
            'allowlisted': [row for row in detail if row['scope'] == 'allowlist'],
            'ungated_unlink': [row['model'] for row in detail
                               if not row['unlink_gated']],
        }
