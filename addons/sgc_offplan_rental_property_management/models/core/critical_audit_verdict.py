# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

"""Critical-Change Audit — scheduled verification verdict log (D13, blocker 2).

One row per verification run.  This model is deliberately NOT wired to
``sgc.critical.audit.mixin``: the verifier's own log must never write into the
chain it verifies, or every run would grow the chain and verification could
never be quiescent.  ``_capture_coverage()`` in the report excludes this model
from the coverage denominator for the same reason.

Two hard-won constraints are encoded here:

* ``_table`` is declared explicitly.  Odoo derives a table name from ``_name``
  and validates it against PostgreSQL's 63-byte NAMEDATALEN-1 ceiling at
  registry load; the derived name for an ``sgc.critical.audit.*`` model is long
  enough to abort the load, which is what took the tenant to HTTP 422 once
  already.  The ceiling is a compile-time Postgres constant and cannot be raised
  at runtime.
* ACL rows exist for this model (``security/ir.model.access.csv``).  Model
  access does not create record rules, and zero ACL rows means every non-admin
  caller gets AccessError.

Transaction design (the core requirement of 0.3.3): verification runs on its own
cursor, the verdict is persisted on a second, never-aborted cursor, and alert
delivery runs on a third.  If ``verify_chain()`` raises, the first cursor's
transaction aborts; the second does not see that abort and the verdict still
lands.  If *delivery* fails (e.g. a mail constraint), the verdict is already
committed and is not lost — that failure mode was found by the T2 negative test
and is why delivery is isolated here.
"""

import logging
import time

from odoo import api, fields, models, SUPERUSER_ID
from odoo.exceptions import AccessError

from .critical_audit_chain import (
    ATTESTABLE_EPOCH_CHAIN_NO,
    EXPECTED_UNATTESTABLE,
)

_logger = logging.getLogger(__name__)

# Evidence columns: the record that the chain once failed.  These are immutable
# once written, at the ORM and at the database (see migrations/19.0.2.43).  Only
# the two delivery columns (alert_fired, alert_class) and mail.thread's own
# bookkeeping may be updated after creation.  An auditor's log is the hardest
# thing in the estate to alter, or it is not an auditor's log.
IMMUTABLE_FIELDS = frozenset({
    'run_at', 'trigger', 'verdict', 'ok', 'event_count', 'last_chain_no',
    'gaps', 'collisions', 'attested', 'unattestable',
    'unattestable_beyond_epoch', 'first_divergence', 'coverage', 'duration_ms',
    'error_text', 'company_id', 'tenant_uuid',
})

# ir.config_parameter keys (no credential values are ever written here).
ALERT_USER_PARAM = 'sgc_rent_mt.audit_alert_user_id'
LAST_SUCCESS_PARAM = 'sgc_rent_mt.audit_last_success_at'

# Forward provision: above this many events the verifier should yield between
# chunks with self._commit_progress() to stay clear of the database-level cron
# statement limit.  The production chain is 50 events, an order of magnitude
# below this, so the call is not exercised yet.  Recorded so the next engineer
# does not have to rediscover the ceiling.
COMMIT_PROGRESS_THRESHOLD = 5000

VERDICT_MODEL = 'sgc.critical.audit.verdict'


class CriticalAuditVerdict(models.Model):
    _name = VERDICT_MODEL
    # mail.thread + mail.activity.mixin so the verdict can carry a real
    # mail.activity: mail.activity.create() calls message_notify() on the
    # linked record's model, which only exists on mail.thread. Without it the
    # alert insert raises AttributeError (found by T2). Neither mixin writes to
    # the audit chain, and this model is excluded from the coverage denominator.
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Critical Audit Verification Verdict'
    _table = 'sgc_audit_verdict'
    _order = 'run_at desc, id desc'

    run_at = fields.Datetime(
        string='Run At', required=True, default=fields.Datetime.now, index=True,
    )
    trigger = fields.Selection(
        [('cron', 'Cron'), ('manual', 'Manual'), ('test', 'Test')],
        string='Trigger', required=True, default='manual', index=True,
    )
    verdict = fields.Selection(
        [('verified', 'Verified'), ('partial', 'Partial'),
         ('broken', 'Broken'), ('error', 'Error')],
        string='Verdict', required=True, index=True,
    )
    ok = fields.Boolean(string='OK')
    event_count = fields.Integer(string='Events')
    last_chain_no = fields.Integer(string='Head')
    gaps = fields.Integer(string='Gaps')
    collisions = fields.Integer(string='Collisions')
    attested = fields.Integer(string='Attested')
    unattestable = fields.Integer(string='Unattestable')
    unattestable_beyond_epoch = fields.Integer(string='Unattestable Beyond Epoch')
    first_divergence = fields.Text(string='First Divergence')
    coverage = fields.Char(string='Coverage')
    duration_ms = fields.Integer(string='Duration (ms)')
    alert_fired = fields.Boolean(string='Alert Fired')
    alert_class = fields.Char(string='Alert Class')
    error_text = fields.Text(string='Error')
    outgoing_failures = fields.Integer(
        string='Outgoing Mail Failures',
        help='mail.mail rows in state exception when the verdict was written. '
             'Surfaced in the report so a silently failing outgoing queue is '
             'visible. Alert receipt does NOT depend on this: it is the '
             'mail.activity row, which needs no mail server.',
    )
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True, ondelete='cascade',
    )
    tenant_uuid = fields.Char(string='Tenant UUID', size=36, index=True)

    # ------------------------------------------------------------- immutability
    def write(self, vals, **kwargs):
        """Evidence columns are append-only; only delivery state may change.

        Guarded at the field level rather than by blocking write entirely,
        because mail.thread's own bookkeeping and the two delivery columns are
        legitimate post-create writes.  Every column that records WHAT the
        verifier found is immutable.
        """
        touched = IMMUTABLE_FIELDS.intersection(vals)
        if touched:
            raise AccessError(
                'Verification verdict evidence is append-only; cannot alter %s.'
                % ', '.join(sorted(touched)))
        return super().write(vals, **kwargs)

    def unlink(self, **kwargs):
        """The record that the chain once failed must never be deletable."""
        raise AccessError(
            'Verification verdict rows are append-only and cannot be deleted.')

    # ------------------------------------------------------------- alert logic
    def _alert_reasons(self):
        """Exact alert predicate (0.3.4).  Partial alone is NOT an alert.

        A ``partial`` verdict is the current healthy state of this estate: 15
        rows predate canonical-payload persistence and are expected to be
        unattestable.  Alerting on it would train the operator to ignore the
        control, which is worse than no control.
        """
        reasons = []
        if self.error_text:
            reasons.append(('error', 'Verification raised: %s' % self.error_text))
            return reasons
        if self.gaps > 0:
            reasons.append(('gap', '%s missing chain number(s) below the head' % self.gaps))
        if self.collisions > 0:
            reasons.append(('collision', '%s collision(s) in chain numbering' % self.collisions))
        if self.first_divergence:
            reasons.append(('divergence', 'First divergence: %s' % self.first_divergence))
        if self.last_chain_no != self.event_count:
            reasons.append((
                'head_mismatch',
                'head %s != event count %s' % (self.last_chain_no, self.event_count),
            ))
        if self.unattestable > EXPECTED_UNATTESTABLE:
            reasons.append((
                'unattestable_growth',
                '%s unattestable rows exceeds the disclosed baseline of %s'
                % (self.unattestable, EXPECTED_UNATTESTABLE),
            ))
        if self.unattestable_beyond_epoch > 0:
            reasons.append((
                'unattestable_beyond_epoch',
                '%s unattestable row(s) beyond the disclosed epoch (chain #%s)'
                % (self.unattestable_beyond_epoch, ATTESTABLE_EPOCH_CHAIN_NO),
            ))
        return reasons

    # ------------------------------------------------------------- recipients
    @api.model
    def _alert_recipient(self):
        """Configured alert user, defaulting to the database admin.

        Never guessed: the recipient is an explicit ir.config_parameter
        (``sgc_rent_mt.audit_alert_user_id``) with a deterministic fallback.
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(ALERT_USER_PARAM)
        user = None
        if raw:
            try:
                user = self.env['res.users'].sudo().browse(int(raw)).exists()
            except (TypeError, ValueError):
                _logger.error(
                    '%s is not an integer user id; falling back to the admin user.',
                    ALERT_USER_PARAM,
                )
        if not user:
            user = self.env.ref('base.user_admin', raise_if_not_found=False)
        return user

    # ------------------------------------------------------------- delivery
    @api.model
    def _notify(self, verdict, reasons):
        """Deliver one open mail.activity per (tenant, alert class), throttled.

        A persistently broken chain must not create an activity every run: that
        is table bloat and, worse, alert fatigue.  An activity already open for
        the same tenant and class is updated in place (moved to the newest
        verdict row, deadline refreshed) rather than duplicated.

        Odoo's ``mail.activity.res_model`` is a readonly related field over
        ``res_model_id``; writing ``res_model`` directly leaves it NULL and
        violates ``mail_activity_check_res_id_is_set_if_model``, which is what
        the T2 negative test caught.  Both ``res_model_id`` and ``res_id`` are
        set here.

        Returns True if any activity was created or updated.
        """
        user = self._alert_recipient()
        if not user:
            _logger.error('No alert recipient available; alert not delivered.')
            return False
        Activity = self.env['mail.activity'].sudo()
        model = self.env['ir.model'].sudo()._get(VERDICT_MODEL)
        activity_type = self.env.ref('mail.mail_activity_data_todo', raise_if_not_found=False)
        delivered = False
        for alert_class, message in reasons:
            summary = '[SGC AUDIT ALERT] %s | tenant %s' % (alert_class, verdict.tenant_uuid or '?')
            body = (
                '<b>Critical audit chain alert: %s</b><br/>'
                'Verdict: %s (head %s, events %s, gaps %s, collisions %s, '
                'attested %s, unattestable %s)<br/>%s'
                % (alert_class, verdict.verdict, verdict.last_chain_no,
                   verdict.event_count, verdict.gaps, verdict.collisions,
                   verdict.attested, verdict.unattestable, message)
            )
            existing = Activity.search(
                [
                    ('res_model_id', '=', model.id),
                    ('user_id', '=', user.id),
                    ('summary', '=', summary),
                ],
                limit=1,
            )
            if existing:
                existing.write({
                    'res_id': verdict.id,
                    'note': body,
                    'date_deadline': fields.Date.context_today(verdict),
                })
            else:
                Activity.create({
                    'res_model_id': model.id,
                    'res_id': verdict.id,
                    'user_id': user.id,
                    'summary': summary,
                    'note': body,
                    'activity_type_id': activity_type.id if activity_type else False,
                    'date_deadline': fields.Date.context_today(verdict),
                })
            delivered = True
            _logger.error('SGC audit alert [%s] delivered to %s: %s', alert_class, user.login, message)
        return delivered

    # ------------------------------------------------------------- builder
    @api.model
    def _build_verdict(self, env, verification, error_text, company, tenant_uuid,
                       trigger, duration_ms, coverage):
        vals = {
            'trigger': trigger,
            'company_id': company.id,
            'tenant_uuid': tenant_uuid,
            'duration_ms': duration_ms,
            'coverage': coverage,
            'error_text': error_text,
        }
        try:
            vals['outgoing_failures'] = env['mail.mail'].sudo().search_count(
                [('state', '=', 'exception')])
        except Exception:  # never let a metric break the verdict
            vals['outgoing_failures'] = 0
        if error_text:
            vals.update({
                'verdict': 'error', 'ok': False,
                'event_count': 0, 'last_chain_no': 0, 'gaps': 0, 'collisions': 0,
                'attested': 0, 'unattestable': 0, 'unattestable_beyond_epoch': 0,
                'first_divergence': False,
            })
        else:
            div = verification.get('first_divergence')
            vals.update({
                'verdict': verification.get('verdict') or 'error',
                'ok': bool(verification.get('ok')),
                'event_count': verification.get('events', 0),
                'last_chain_no': verification.get('last_chain_no', 0),
                'gaps': verification.get('gaps', 0),
                'collisions': len(verification.get('collisions') or []),
                'attested': verification.get('attested', 0),
                'unattestable': len(verification.get('unattestable') or []),
                'unattestable_beyond_epoch': len(verification.get('unattestable_beyond_epoch') or []),
                'first_divergence': (
                    'chain #%s (event %s): expected %s, stored %s'
                    % (div.get('chain_no'), div.get('event_id'),
                       str(div.get('expected'))[:16], str(div.get('stored'))[:16])
                    if div else False
                ),
            })
        return env[VERDICT_MODEL].sudo().create(vals)

    # ------------------------------------------------------------- progress yield
    @api.model
    def _commit_progress(self):
        """Yield the verification transaction to the database (0.3.3 provision).

        Implemented 2026-10-05: the method was referenced by
        ``_run_scheduled_verification()`` since Wave 0.3 (19.0.2.42) but was
        never defined here, so once the chain crossed
        ``COMMIT_PROGRESS_THRESHOLD`` every scheduled run raised
        ``AttributeError``, persisted ``verdict=error`` and alerted the admin
        once per hour (HANDOVER_20261005.md, section 8).

        The only call site runs after ``verify_chain()`` has returned, on the
        verification cursor, one statement before the enclosing
        ``with registry.cursor()`` would commit on clean exit anyway
        (``sql_db.Cursor.__exit__`` commits when no exception was raised), so
        this commit changes nothing observable about verification atomicity.
        If verification is ever chunked, move the call into the chunk loop
        and revisit that decision explicitly.
        """
        self.env.cr.commit()

    # ------------------------------------------------------------- entry point
    @api.model
    def _run_scheduled_verification(self, trigger='cron'):
        """Run verify_chain() and persist a verdict.  NEVER raises.

        A cron that raises is deactivated by Odoo after repeated failures (three
        consecutive errors/timeouts counts as failed; five consecutive failures
        over at least seven days deactivates the action and notifies the DB
        admin).  A raising cron would therefore switch off the estate's only
        chain-failure detection control precisely when the chain is broken.

        Three transactions, deliberately:
          1. verification — its own cursor; a raise aborts only this one
          2. verdict persistence — separate cursor, committed before delivery
          3. alert delivery — separate cursor; a failure here cannot lose the
             verdict (found by T2)
        Returns the new verdict id, or False if even persistence failed.
        """
        registry = self.env.registry
        started = time.monotonic()
        company = self.env.company or self.env.ref('base.main_company')
        tenant_uuid = None
        verification = None
        error_text = None
        coverage = ''

        # --- phase 1: verification, on its own cursor ------------------------
        try:
            with registry.cursor() as cr_v:
                env_v = api.Environment(cr_v, SUPERUSER_ID, {})
                _tid, tenant_uuid = env_v['sgc.critical.audit.tenant']._ensure_tenant(env_v)
                verification = env_v['sgc.critical.audit.chain'].verify_chain(
                    env_v, tenant_uuid, company.id)
                cov = env_v['report.sgc_offplan_rental_property_management.'
                             'report_critical_audit_verification_document']._capture_coverage()
                coverage = '%s/%s' % (cov.get('wired'), cov.get('total'))
                if verification.get('events', 0) > COMMIT_PROGRESS_THRESHOLD:
                    # Forward provision (0.3.3): yield to the database before the
                    # cron statement/time budget becomes a risk.  Not exercised at
                    # 50 events; the call is here so the next engineer does not
                    # have to rediscover the database-level cron ceiling.
                    env_v[VERDICT_MODEL]._commit_progress()
        except Exception as exc:  # noqa: BLE001 - the cron must never raise
            error_text = '%s: %s' % (type(exc).__name__, exc)
            _logger.error('Critical audit scheduled verification raised: %s', error_text)

        duration_ms = int((time.monotonic() - started) * 1000)

        # --- phase 2: persist the verdict (survives any delivery failure) ----
        verdict_id = False
        try:
            with registry.cursor() as cr_l:
                env_l = api.Environment(cr_l, SUPERUSER_ID, {})
                verdict = self._build_verdict(
                    env_l, verification, error_text, company, tenant_uuid,
                    trigger, duration_ms, coverage)
                reasons = verdict._alert_reasons()
                verdict.alert_class = ','.join(sorted({c for c, _m in reasons})) or False
                if not reasons:
                    env_l['ir.config_parameter'].sudo().set_param(
                        LAST_SUCCESS_PARAM, fields.Datetime.now())
                verdict_id = verdict.id
                _logger.info(
                    'SGC audit verification [%s]: verdict=%s head=%s events=%s '
                    'gaps=%s collisions=%s attested=%s unattestable=%s alerts=%s',
                    trigger, verdict.verdict, verdict.last_chain_no, verdict.event_count,
                    verdict.gaps, verdict.collisions, verdict.attested,
                    verdict.unattestable, verdict.alert_class or 'none',
                )
        except Exception as exc:  # noqa: BLE001 - the cron must never raise
            _logger.error(
                'Critical audit verdict could not be persisted (verification '
                'outcome was %s): %s: %s',
                error_text or (verification or {}).get('verdict'), type(exc).__name__, exc,
            )
            return False

        # --- phase 3: delivery, isolated from the verdict --------------------
        try:
            with registry.cursor() as cr_a:
                env_a = api.Environment(cr_a, SUPERUSER_ID, {})
                v = env_a[VERDICT_MODEL].sudo().browse(verdict_id)
                reasons = v._alert_reasons()
                if reasons and v._notify(v, reasons):
                    v.alert_fired = True
                    _logger.error(
                        'SGC audit alert fired for verdict %s: %s',
                        verdict_id, v.alert_class)
        except Exception as exc:  # noqa: BLE001 - the cron must never raise
            _logger.error(
                'Critical audit alert delivery failed for verdict %s (verdict is '
                'persisted regardless): %s: %s', verdict_id, type(exc).__name__, exc,
            )
        return verdict_id
