# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

"""Critical-Change Audit — chain head (design §4.7, §7).

One row per (tenant_uuid, company_id).  The service advances the head in the
same transaction that inserts each audit event [C1].  Rows are immutable from
the model layer: every write/unlink raises, and all head advancement happens
through this module's SQL helpers (serialized by a row lock, with a
pg_advisory_xact_lock fallback).
"""

import logging

from odoo import fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

_GENESIS_HASH = '0' * 64

_TABLE = 'sgc_critical_audit_chain'

# ---------------------------------------------------------------------------
# Disclosed epoch baseline (Wave 0.3.1).
#
# Events at or below ATTESTABLE_EPOCH_CHAIN_NO were written before
# canonical-payload persistence landed on 2026-09-15.  Their row_hash cannot be
# recomputed from the stored row because the writer hashed Python values that a
# round-trip through the row's text columns does not preserve.  They are
# EXPECTED to be unattestable and are therefore not an alert condition.
#
# These are disclosure constants.  No chain row is modified, rehashed or
# re-baselined to make them verify.  The verification report states the epoch so
# a reader sees "attestable from event 16" rather than only "partial".
# ---------------------------------------------------------------------------
ATTESTABLE_EPOCH_CHAIN_NO = 15
EXPECTED_UNATTESTABLE = 15


class CriticalAuditChain(models.Model):
    _name = 'sgc.critical.audit.chain'
    _description = 'Critical Audit Chain Head'
    _log_access = False

    tenant_uuid = fields.Char(string='Tenant UUID', size=36, required=True, index=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        ondelete='restrict',
    )
    last_chain_no = fields.Integer(string='Last Chain No', required=True, default=0)
    last_hash = fields.Char(string='Last Hash', size=64, required=True, default=_GENESIS_HASH)
    anchored_root = fields.Char(string='Anchored Root Hash', size=64)
    anchored_at = fields.Datetime(string='Anchored At')
    anchored_by = fields.Many2one('res.users', string='Anchored By', ondelete='restrict')

    # Odoo 19: _sql_constraints was removed; declare SQL constraints as
    # models.Constraint table objects (model_classes.py logs a warning and
    # silently ignores the legacy attribute).
    _chain_unique_per_tenant_company = models.Constraint(
        'UNIQUE (tenant_uuid, company_id)',
        'A chain head already exists for this tenant and company.',
    )

    # ------------------------------------------------------------- SQL helpers
    @staticmethod
    def _advisory_lock_key(tenant_uuid, company_id):
        return 'sgc_audit_chain|%s|%s' % (tenant_uuid, company_id)

    @classmethod
    def _bootstrap(cls, env, tenant_uuid, company_id):
        """INSERT ... ON CONFLICT DO NOTHING, then SELECT ... FOR UPDATE.

        Returns the chain head row as a dict.  Serializable under concurrency:
        the row lock (with advisory-lock fallback) guarantees only one advance
        per chain per transaction.
        """
        cr = env.cr
        cr.execute(
            """
            INSERT INTO %s
                (tenant_uuid, company_id, last_chain_no, last_hash)
            VALUES (%%s, %%s, 0, %%s)
            ON CONFLICT (tenant_uuid, company_id) DO NOTHING
            """ % _TABLE,
            (tenant_uuid, company_id, _GENESIS_HASH),
        )
        try:
            cr.execute(
                """
                SELECT id, tenant_uuid, company_id, last_chain_no, last_hash,
                       anchored_root, anchored_at, anchored_by
                FROM %s
                WHERE tenant_uuid = %%s AND company_id = %%s
                FOR UPDATE
                """ % _TABLE,
                (tenant_uuid, company_id),
            )
        except Exception:
            # pg_advisory_xact_lock fallback: serialize on a stable per-chain key
            # if the row lock is unavailable (design §4.7).
            cr.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', (cls._advisory_lock_key(tenant_uuid, company_id),))
            cr.execute(
                """
                SELECT id, tenant_uuid, company_id, last_chain_no, last_hash,
                       anchored_root, anchored_at, anchored_by
                FROM %s
                WHERE tenant_uuid = %%s AND company_id = %%s
                """ % _TABLE,
                (tenant_uuid, company_id),
            )
        row = cr.dictfetchone()
        if row is None:  # pragma: no cover - UNIQUE constraint makes this impossible
            raise RuntimeError('Audit chain bootstrap failed for tenant %s, company %s' % (tenant_uuid, company_id))
        return row

    @classmethod
    def head(cls, env, tenant_uuid, company_id):
        """Lazy-bootstrap and return the current head (chain_no, last_hash)."""
        row = cls._bootstrap(env, tenant_uuid, company_id)
        return row['last_chain_no'], row['last_hash']

    @classmethod
    def advance(cls, env, tenant_uuid, company_id, chain_no, row_hash):
        """Advance the head to (chain_no, row_hash) — one row, one tx.

        The head is re-locked FOR UPDATE so a concurrent capture cannot interleave
        two events with the same chain_no.
        """
        cr = env.cr
        # Row-lock path (primary).
        cr.execute(
            """
            UPDATE %s SET last_chain_no = %%s, last_hash = %%s
            WHERE tenant_uuid = %%s AND company_id = %%s
              AND last_chain_no = %%s - 1
            RETURNING id
            """ % _TABLE,
            (chain_no, row_hash, tenant_uuid, company_id, chain_no),
        )
        updated = cr.fetchone() is not None
        if not updated:
            # Lock contention or a gap/collision detected — fail closed.
            raise RuntimeError(
                'Audit chain head cannot be advanced to %s (tenant %s, company %s). '
                'A concurrent capture probably interleaved; capture rolled back.'
                % (chain_no, tenant_uuid, company_id)
            )
        return True

    @classmethod
    def verify_chain(cls, env, tenant_uuid, company_id):
        """Walk events in chain_no order, recompute row_hash, report first divergence.

        Returns a dict.  Terminology: a row whose ``canonical_payload`` is empty
        is **unattestable** (the verifier lacks the bytes to recompute its hash);
        it is not a divergence.  ``unverifiable`` is not used anywhere in this
        module or its reports (P5, Entry 31).

        ``gaps`` is ``last_chain_no - event_count`` (clamped at 0).  The
        ``UNIQUE (tenant_uuid, company_id, chain_no)`` constraint means no two
        rows share a chain number, so the event count is also the count of
        distinct chain numbers; anything below the head that is absent is a gap.
        """
        cr = env.cr
        events = env['sgc.critical.audit.event'].sudo().search(
            [
                ('tenant_uuid', '=', tenant_uuid),
                ('company_id', '=', company_id),
            ],
            order='chain_no asc, id asc',
        )
        result = {
            'ok': True,
            'verdict': 'verified',
            'events': len(events),
            'attested': 0,
            'unattestable': [],
            'unattestable_display': '',
            'unattestable_beyond_epoch': [],
            'last_chain_no': events[-1].chain_no if events else 0,
            'gaps': 0,
            'first_divergence': None,
            'collisions': [],
            'attestable_epoch_chain_no': ATTESTABLE_EPOCH_CHAIN_NO,
            'expected_unattestable': EXPECTED_UNATTESTABLE,
        }
        prev_hash = _GENESIS_HASH
        seen = set()
        service = None
        for ev in events:
            if ev.chain_no in seen:
                result['collisions'].append(ev.chain_no)
                result['ok'] = False
            seen.add(ev.chain_no)
            if service is None:
                # Late import: avoid module-load cycle with the services package.
                from odoo.addons.sgc_offplan_rental_property_management.services \
                    import sgc_audit_internal_service as _svc
                service = _svc
            if not ev.canonical_payload:
                # Written before canonical-payload persistence (2026-09-15).
                # The payload cannot be reconstructed byte-identically -- the
                # writer hashed Python values (e.g. None) that a round-trip
                # through the row's text columns does not preserve -- so these
                # rows are reported as unattestable, NOT as divergences. No
                # chain row is modified to make them verify.
                result['unattestable'].append(ev.chain_no)
                if ev.chain_no > ATTESTABLE_EPOCH_CHAIN_NO:
                    result['unattestable_beyond_epoch'].append(ev.chain_no)
                prev_hash = ev.row_hash
                continue
            expected = service.row_hash(prev_hash, ev.canonical_payload)
            if ev.row_hash != expected:
                result['first_divergence'] = {
                    'chain_no': ev.chain_no,
                    'event_id': ev.id,
                    'expected': expected,
                    'stored': ev.row_hash,
                }
                result['ok'] = False
                break
            prev_hash = ev.row_hash
            result['attested'] += 1
        if not result['ok']:
            result['verdict'] = 'broken'
        elif result['unattestable']:
            result['verdict'] = 'partial'
        else:
            result['verdict'] = 'verified'
        result['unattestable_display'] = ', #'.join(
            str(n) for n in result['unattestable'][:25])
        result['gaps'] = max(0, result['last_chain_no'] - result['events'])
        return result

    # ------------------------------------------------------------- immutability
    def create(self, vals_list, **kwargs):
        raise AccessError(
            'Audit chain rows are created through the internal SQL bootstrap only.'
        )

    def write(self, vals, **kwargs):
        raise AccessError('Audit chain rows are immutable from the model layer (SQL advance only).')

    def unlink(self, **kwargs):
        raise AccessError('Audit chain rows cannot be deleted.')

    def copy(self, default=None):
        raise AccessError('Audit chain rows cannot be copied.')
