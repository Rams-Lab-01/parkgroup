import logging

from odoo import api, fields, models

from ..services import specs

_logger = logging.getLogger(__name__)


class PgreSyncRunner(models.Model):
    """Singleton control panel for the PGRE sync engine.

    Holds no business data of its own: it is the UI anchor for the admin
    actions (run poll / run reconcile / dry-run diff) and the cron entry
    points. A single row is created lazily the first time anyone opens the
    Control view.
    """

    _name = 'pgre.sync.runner'
    _description = 'PGRE Sync Runner (Control)'

    last_poll = fields.Datetime(string='Last Poll', readonly=True)
    last_reconcile = fields.Datetime(string='Last Reconcile', readonly=True)
    last_poll_result = fields.Text(string='Last Poll Result', readonly=True)
    last_reconcile_result = fields.Text(string='Last Reconcile Result', readonly=True)

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------
    @api.model
    def browse_singleton(self):
        """Return the one control record, creating it on first use."""
        record = self.search([], limit=1)
        if not record:
            record = self.create({})
        return record

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _log_info(self, summary, payload=None):
        self.env['pgre.sync.log'].log_info(
            model=None, pgre_id=0, vps_id=0, dry_run=False, summary=summary,
            payload=payload)

    def _alert_email(self, subject, body):
        email = specs.get_alert_email(self.env)
        if not email:
            return
        self.env['mail.mail'].sudo().create({
            'subject': subject,
            'body_html': body,
            'email_to': email,
            'author_id': self.env.ref('base.partner_admin', raise_if_not_found=False).id,
        }).send(raise_exception=False)

    # ------------------------------------------------------------------
    # Engine entry points
    # ------------------------------------------------------------------
    @api.model
    def _engine_enabled(self):
        return specs.get_enabled(self.env)

    @api.model
    def _build_remote(self):
        from ..services.pgre_remote import PgreRemote
        return PgreRemote.from_env(self.env)

    @api.model
    def run_poll(self, dry_run_override=None):
        """Run one poll cycle. Returns (counts dict, batch ts) or None when
        disabled / credentials missing."""
        if not self._engine_enabled():
            self._log_info('Sync engine is disabled (pgre_sync.enabled != True).')
            return None
        started = fields.Datetime.now()
        try:
            remote = self._build_remote()
            remote.authenticate()
        except Exception as exc:  # auth/config problems are fatal for the cycle
            self.env['pgre.sync.log'].log_error(
                model=None, pgre_id=0, vps_id=0, dry_run=False,
                summary='Poll aborted: cannot reach PGRE source.',
                error=exc)
            return None
        from ..services.poller import run_poll
        result = run_poll(self.env, remote=remote, dry_run_override=dry_run_override)
        summary = result.get('summary', '')
        self.env['pgre.sync.log'].log_info(
            model=None, pgre_id=0, vps_id=0, dry_run=bool(dry_run_override),
            summary='Poll finished: %s' % summary, payload=result)
        record = self.browse_singleton()
        record.write({
            'last_poll': started,
            'last_poll_result': summary,
        })
        return result

    @api.model
    def run_reconcile(self):
        if not self._engine_enabled():
            self._log_info('Sync engine is disabled (pgre_sync.enabled != True).')
            return None
        try:
            remote = self._build_remote()
            remote.authenticate()
        except Exception as exc:
            self.env['pgre.sync.log'].log_error(
                model=None, pgre_id=0, vps_id=0, dry_run=False,
                summary='Reconcile aborted: cannot reach PGRE source.',
                error=exc)
            return None
        from ..services.reconciler import run_reconcile
        result = run_reconcile(self.env, remote=remote)
        summary = result.get('summary', '')
        self.env['pgre.sync.log'].log_info(
            model=None, pgre_id=0, vps_id=0, dry_run=False,
            summary='Reconcile finished: %s' % summary, payload=result)
        flagged = result.get('deleted', 0) + result.get('flagged', 0)
        if flagged:
            self._alert_email(
                'PGRE Sync: reconcile flagged %s record(s)' % flagged,
                '<p>PGRE nightly reconcile flagged %s record(s). See the sync log '
                'for details: deleted=%s, flagged=%s.</p>'
                % (flagged, result.get('deleted', 0), result.get('flagged', 0)))
        record = self.browse_singleton()
        record.write({
            'last_reconcile': fields.Datetime.now(),
            'last_reconcile_result': summary,
        })
        return result

    @api.model
    def run_post_test(self):
        """Exercise the REAL write path - create, post, everything - then roll
        the whole thing back.

        A plain dry-run is not a safety gate: it never calls ``action_post()``,
        so it never triggers Odoo's cross-company consistency checks. Those are
        the failures that matter, and they only appear once a record is posted.

        Everything runs inside one manual savepoint that is rolled back at the
        end, so the database is left exactly as it was. The captured log is
        written afterwards, once the rollback has happened.
        """
        if not self._engine_enabled():
            self._log_info('Post-test skipped: engine is disabled.')
            return None
        try:
            remote = self._build_remote()
            remote.authenticate()
        except Exception as exc:
            self.env['pgre.sync.log'].log_error(
                model=None, pgre_id=0, vps_id=0, dry_run=False,
                summary='Post-test aborted: cannot reach PGRE source.', error=exc)
            return None

        from ..services.poller import run_poll
        capture = []
        # Explicit SQL savepoint: Odoo's cursor wrapper has no manual mode, and
        # the whole run must be discardable after it has POSTED real records.
        sp = 'pgre_sync_post_test'
        self.env.cr.execute('SAVEPOINT %s' % sp)
        try:
            # dry_run=False: this must POST for the test to mean anything.
            result = run_poll(self.env, remote=remote, dry_run_override=False,
                              capture=capture)
        except Exception as exc:
            _logger.exception('PGRE post-test crashed')
            result = {'error': str(exc)}
        finally:
            try:
                # Push pending ORM writes into the savepoint, then discard them.
                self.env.flush_all()
            except Exception:
                _logger.exception('PGRE post-test flush failed')
            self.env.cr.execute('ROLLBACK TO SAVEPOINT %s' % sp)
            self.env.cr.execute('RELEASE SAVEPOINT %s' % sp)
            self.env.invalidate_all()

        # The DB is back to its starting state; persist the report now.
        stats = {'captured': len(capture)}
        for entry in capture:
            try:
                self.env['pgre.sync.log'].log(
                    model=entry.get('model'), pgre_id=entry.get('pgre_id') or 0,
                    vps_id=entry.get('vps_id') or 0,
                    action=entry.get('action') or 'info', dry_run=False,
                    summary='[POST-TEST] %s' % (entry.get('summary') or ''),
                    payload=entry.get('payload'))
            except Exception:
                _logger.exception('PGRE post-test report write failed')
        summary = (result or {}).get('summary', '')
        self.env['pgre.sync.log'].log_info(
            model=None, pgre_id=0, vps_id=0, dry_run=False,
            summary='POST-TEST completed and ROLLED BACK (no data kept): %s'
                    % summary, payload={'result': result, 'report_rows': stats})
        self.browse_singleton().write({'last_poll': fields.Datetime.now(),
                                       'last_poll_result': '[post-test] %s' % summary})
        return result

    # ------------------------------------------------------------------
    # Cron entry points (kill-switch + no-exception guarantees)
    # ------------------------------------------------------------------
    @api.model
    def cron_poll(self):
        try:
            self.run_poll()
        except Exception:
            _logger.exception('PGRE poll cron failed (engine state preserved).')
            self.env['pgre.sync.log'].log_info(
                model=None, pgre_id=0, vps_id=0, dry_run=False,
                summary='Poll cron crashed - see server log for the traceback.')
        return True

    @api.model
    def cron_reconcile(self):
        try:
            self.run_reconcile()
        except Exception:
            _logger.exception('PGRE reconcile cron failed (engine state preserved).')
            self.env['pgre.sync.log'].log_info(
                model=None, pgre_id=0, vps_id=0, dry_run=False,
                summary='Reconcile cron crashed - see server log for the traceback.')
        return True

    # ------------------------------------------------------------------
    # Manual UI actions
    # ------------------------------------------------------------------
    def action_run_poll(self):
        self.ensure_one()
        self.run_poll()
        return {
            'type': 'ir.actions.act_window',
            'name': 'PGRE Sync Log',
            'res_model': 'pgre.sync.log',
            'view_mode': 'list,form',
        }

    def action_run_reconcile(self):
        self.ensure_one()
        self.run_reconcile()
        return {
            'type': 'ir.actions.act_window',
            'name': 'PGRE Sync Log',
            'res_model': 'pgre.sync.log',
            'view_mode': 'list,form',
        }

    def action_dry_run_diff(self):
        self.ensure_one()
        self.run_poll(dry_run_override=True)
        return {
            'type': 'ir.actions.act_window',
            'name': 'PGRE Sync Dry-Run Diff',
            'res_model': 'pgre.sync.log',
            'view_mode': 'list,form',
            'domain': [('dry_run', '=', True)],
        }

    def action_post_test(self):
        """Real write path, fully rolled back.

        Deliberately NOT exposed as a UI button. This opens a long transaction
        inside a web worker; running it there has been observed to kill the
        worker. Invoke it from a separate process instead:

            docker exec -i sgc_rent_mt odoo shell -d sgc_mt_parkgroup --no-http
            >>> env['pgre.sync.runner'].run_post_test()
        """
        self.ensure_one()
        self.run_post_test()
        return {
            'type': 'ir.actions.act_window',
            'name': 'PGRE Sync Post-Test Report',
            'res_model': 'pgre.sync.log',
            'view_mode': 'list,form',
            'domain': [('summary', 'like', '[POST-TEST]')],
        }
