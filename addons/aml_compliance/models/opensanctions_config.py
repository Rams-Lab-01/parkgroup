# -*- coding: utf-8 -*-

import logging
from datetime import datetime
import csv
import io
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import requests
from requests.exceptions import ChunkedEncodingError, RequestException

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)

TRUSTED_IMPORT_HOSTS = {'data.opensanctions.org'}
MAX_IMPORT_BYTES = 80 * 1024 * 1024
LARGE_IMPORT_BATCH = 1000         # Rows per bulk SQL upsert + commit
LARGE_DATASET_MAX_ROWS = 5_000_000  # Safety cap — default dataset is ~1.2 M rows
FULL_IMPORT_MAX_RETRIES = 5
FULL_IMPORT_RETRY_WAIT_SEC = 10


class AmlOpenSanctionsConfig(models.Model):
    _name = 'aml.opensanctions.config'
    _description = 'OpenSanctions / Yente Configuration'
    _rec_name = 'name'

    name = fields.Char(required=True, default='Default OpenSanctions Config')
    active = fields.Boolean(default=True)

    mode = fields.Selection([
        ('cloud', 'OpenSanctions Cloud API'),
        ('selfhosted', 'Self-Hosted Yente'),
    ], required=True, default='cloud')

    api_url = fields.Char(
        required=True,
        default='https://api.opensanctions.org',
        help='Base URL of OpenSanctions API or self-hosted yente endpoint.',
    )
    api_key = fields.Char(help='Optional API key for OpenSanctions Cloud.')
    dataset = fields.Char(
        default='default',
        help='Dataset selector for match endpoint (e.g. default, sanctions, peps).',
    )
    algorithm = fields.Selection([
        ('logic-v1', 'logic-v1'),
        ('regression-v1', 'regression-v1'),
    ], default='logic-v1', required=True)
    score_threshold = fields.Float(default=0.70, required=True)
    result_limit = fields.Integer(default=10, required=True)
    timeout = fields.Integer(default=20, required=True)

    connection_status = fields.Selection([
        ('unknown', 'Unknown'),
        ('ok', 'Connected'),
        ('error', 'Error'),
    ], default='unknown', readonly=True)
    status_message = fields.Char(readonly=True)
    last_check = fields.Datetime(readonly=True)
    last_sync_at = fields.Datetime(readonly=True)
    last_sync_summary = fields.Text(readonly=True)
    last_sync_count = fields.Integer(readonly=True)
    local_sanctions_count = fields.Integer(
        string='Local Sanctions Entries',
        compute='_compute_local_sanctions_count',
    )

    @api.depends('last_sync_at')
    def _compute_local_sanctions_count(self):
        count = self.env['aml.sanctions.list'].search_count([('active', '=', True)])
        for rec in self:
            rec.local_sanctions_count = count

    @api.model
    def get_config(self):
        return self.search([('active', '=', True)], limit=1)

    def _base_url(self):
        self.ensure_one()
        return (self.api_url or '').strip().rstrip('/')

    def _headers(self):
        self.ensure_one()
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'ApiKey {self.api_key}'
        return headers

    def _source_from_hit(self, hit):
        datasets = hit.get('datasets') or []
        lower = ','.join(datasets).lower()
        if 'ofac' in lower:
            return 'ofac'
        if 'eu' in lower:
            return 'eu'
        if 'uae' in lower:
            return 'uae_local'
        if 'un' in lower:
            return 'un'
        return 'custom'

    def _assert_manager(self):
        if self.env.is_superuser():
            return
        if not self.env.user.has_group('aml_compliance.group_aml_manager'):
            raise AccessError(_('Only AML Managers can run sanctions imports.'))

    def _safe_text(self, value, max_len=255):
        text = (value or '').strip()
        if not text:
            return ''
        # Drop control chars and normalize whitespace to reduce injection/noise risk.
        text = re.sub(r'[\x00-\x1f\x7f]+', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:max_len]

    def _safe_aliases(self, value, max_len=4000):
        text = self._safe_text(value, max_len=max_len)
        return text

    def _secure_fetch_text(self, url):
        parsed = urlparse(url)
        if parsed.scheme != 'https':
            raise AccessError(_('Blocked non-HTTPS import URL: %s') % url)
        host = (parsed.hostname or '').lower()
        if host not in TRUSTED_IMPORT_HOSTS:
            raise AccessError(_('Blocked untrusted import host: %s') % host)

        response = requests.get(url, timeout=max(self.timeout, 10), stream=True)
        response.raise_for_status()

        chunks = []
        read_bytes = 0
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            read_bytes += len(chunk)
            if read_bytes > MAX_IMPORT_BYTES:
                raise AccessError(_('Import aborted: payload too large (> %s MB).') % (MAX_IMPORT_BYTES // (1024 * 1024)))
            chunks.append(chunk)
        return b''.join(chunks).decode('utf-8-sig', errors='ignore')

    def action_test_connection(self):
        self.ensure_one()
        self._assert_manager()
        now = fields.Datetime.now()
        try:
            # Minimal, cheap check against the configured endpoint.
            payload = {
                'queries': {
                    'q1': {
                        'schema': 'Thing',
                        'properties': {'name': ['Test']},
                    }
                },
                'limit': 1,
                'algorithm': self.algorithm,
                'threshold': self.score_threshold,
            }
            dataset = (self.dataset or 'default').strip() or 'default'
            url = f"{self._base_url()}/match/{dataset}"
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=max(self.timeout, 5),
            )
            response.raise_for_status()
            self.write({
                'connection_status': 'ok',
                'status_message': _('Connection successful.'),
                'last_check': now,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('OpenSanctions'),
                    'message': _('Connection successful.'),
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as exc:
            msg = str(exc)[:500]
            _logger.warning('OpenSanctions connection test failed: %s', msg)
            self.write({
                'connection_status': 'error',
                'status_message': msg,
                'last_check': now,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('OpenSanctions'),
                    'message': _('Connection failed: %s') % msg,
                    'type': 'warning',
                    'sticky': True,
                },
            }

    def match_partner(self, partner):
        self.ensure_one()
        partner_name = (partner.name or '').strip()
        if not partner_name:
            return []

        payload = {
            'queries': {
                'partner': {
                    'schema': 'Person' if (partner.is_company is False) else 'Organization',
                    'properties': {
                        'name': [partner_name],
                    },
                }
            },
            'limit': max(self.result_limit, 1),
            'algorithm': self.algorithm,
            'threshold': max(min(self.score_threshold, 1.0), 0.0),
        }

        if partner.country_id and partner.country_id.code:
            payload['queries']['partner']['properties']['country'] = [partner.country_id.code]

        dataset = (self.dataset or 'default').strip() or 'default'
        url = f"{self._base_url()}/match/{dataset}"

        try:
            response = requests.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=max(self.timeout, 5),
            )
            response.raise_for_status()
            data = response.json() or {}
            # yente returns {responses:{query:[hits...]}} for /match endpoints
            responses = data.get('responses') or {}
            hits = responses.get('partner') or []
            self.write({
                'connection_status': 'ok',
                'status_message': _('Match query succeeded.'),
                'last_check': fields.Datetime.now(),
            })
            return hits
        except Exception as exc:
            msg = str(exc)[:500]
            _logger.warning('OpenSanctions match request failed: %s', msg)
            self.write({
                'connection_status': 'error',
                'status_message': msg,
                'last_check': fields.Datetime.now(),
            })
            return []

    def _upsert_sanctions_entry(self, hit):
        self.ensure_one()

        listed_name = (hit.get('caption') or hit.get('name') or '').strip()
        if not listed_name:
            listed_name = _('Unknown Listed Name')

        entity_id = (hit.get('id') or '').strip()
        source = self._source_from_hit(hit)
        schema = (hit.get('schema') or '').lower()
        listed_type = 'entity'
        if schema in ('person', 'individual'):
            listed_type = 'individual'
        elif schema == 'vessel':
            listed_type = 'vessel'

        domain = [('listed_name', '=', listed_name), ('list_source', '=', source)]
        if entity_id:
            domain = [('un_reference', '=', entity_id), ('list_source', '=', source)]

        entry = self.env['aml.sanctions.list'].search(domain, limit=1)

        values = {
            'listed_name': listed_name,
            'list_source': source,
            'listed_type': listed_type,
            'un_reference': entity_id or False,
            'notes': _('Imported from OpenSanctions match API on %s') % datetime.utcnow().isoformat(),
            'active': True,
        }

        if entry:
            entry.write(values)
            return entry
        return self.env['aml.sanctions.list'].create(values)

    def _upsert_local_entry(self, values):
        """Create or update local sanctions entry from external list rows."""
        model = self.env['aml.sanctions.list']
        listed_name = self._safe_text(values.get('listed_name'), max_len=255)
        list_source = values.get('list_source') or 'custom'
        if not listed_name:
            return False, False

        ref = self._safe_text(values.get('un_reference'), max_len=255)

        # Unique key in this model is (listed_name, list_source), so search by
        # that first to avoid duplicate-key write failures.
        entry = model.search([
            ('list_source', '=', list_source),
            ('listed_name', '=', listed_name),
        ], limit=1)
        if not entry and ref:
            entry = model.search([
                ('list_source', '=', list_source),
                ('un_reference', '=', ref),
            ], limit=1)

        cleaned = {
            'listed_name': listed_name,
            'alias_names': self._safe_aliases(values.get('alias_names')) or False,
            'list_source': list_source,
            'listed_type': values.get('listed_type') or 'individual',
            'nationality': self._safe_text(values.get('nationality')) or False,
            'un_reference': ref or False,
            'notes': self._safe_text(values.get('notes'), max_len=2000) or False,
            'active': True,
        }

        if entry:
            entry.write(cleaned)
            return entry, False
        return model.create(cleaned), True

    def _import_targets_simple_csv(self, url, source_code, source_label):
        """Import OpenSanctions targets.simple.csv feed with security controls."""
        text = self._secure_fetch_text(url)
        reader = csv.DictReader(io.StringIO(text))

        created, updated = 0, 0
        for row in reader:
            name = self._safe_text(row.get('name'), max_len=255)
            if not name:
                continue
            schema = self._safe_text(row.get('schema'), max_len=64).lower()
            if schema in ('organization', 'legalentity', 'company', 'publicbody'):
                listed_type = 'entity'
            elif schema == 'vessel':
                listed_type = 'vessel'
            else:
                listed_type = 'individual'

            ref = self._safe_text(row.get('id'), max_len=255)
            aliases = self._safe_aliases((row.get('aliases') or '').replace(';', ', '))
            nationality = self._safe_text((row.get('countries') or '').split(';')[0], max_len=128)
            notes = self._safe_text(row.get('sanctions') or source_label, max_len=2000)

            _, is_created = self._upsert_local_entry({
                'listed_name': name,
                'alias_names': aliases,
                'list_source': source_code,
                'listed_type': listed_type,
                'nationality': nationality,
                'un_reference': ref,
                'notes': notes,
            })
            if is_created:
                created += 1
            else:
                updated += 1

        return {
            'source': source_label,
            'created': created,
            'updated': updated,
            'total': created + updated,
        }

    def action_import_free_sanctions_lists(self):
        """Import free public sanctions lists into local screening table."""
        self.ensure_one()
        self._assert_manager()

        jobs = [
            ('UN Consolidated', lambda: self._import_targets_simple_csv(
                'https://data.opensanctions.org/datasets/latest/un_sc_sanctions/targets.simple.csv',
                'un',
                'UN Consolidated',
            )),
            ('US OFAC SDN', lambda: self._import_targets_simple_csv(
                'https://data.opensanctions.org/datasets/latest/us_ofac_sdn/targets.simple.csv',
                'ofac',
                'US OFAC SDN',
            )),
            ('EU FSF', lambda: self._import_targets_simple_csv(
                'https://data.opensanctions.org/datasets/latest/eu_fsf/targets.simple.csv',
                'eu',
                'EU Financial Sanctions Files',
            )),
            ('UK FCDO', lambda: self._import_targets_simple_csv(
                'https://data.opensanctions.org/datasets/latest/gb_fcdo_sanctions/targets.simple.csv',
                'custom',
                'UK FCDO Sanctions List',
            )),
        ]

        reports = []
        total = 0
        for source_name, job in jobs:
            try:
                # Isolate each source in its own DB savepoint so one bad feed
                # never aborts the full sync transaction.
                with self.env.cr.savepoint():
                    rep = job()
                reports.append(rep)
                total += rep['total']
            except Exception as exc:
                reports.append({'source': source_name, 'error': str(exc)[:300]})

        lines = []
        for rep in reports:
            if rep.get('error'):
                lines.append(f"- {rep['source']}: ERROR - {rep['error']}")
            else:
                lines.append(
                    f"- {rep['source']}: total={rep['total']} (created={rep['created']}, updated={rep['updated']})"
                )

        summary = '\n'.join(lines)
        self.write({
            'last_sync_at': fields.Datetime.now(),
            'last_sync_summary': summary,
            'last_sync_count': total,
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Sanctions Sync Complete'),
                'message': _('Imported/updated %s records from free public lists.') % total,
                'type': 'success',
                'sticky': False,
            },
        }

    @api.model
    def cron_sync_free_lists(self):
        configs = self.search([('active', '=', True)])
        for conf in configs:
            conf.action_import_free_sanctions_lists()

    # ------------------------------------------------------------------
    # Full OpenSanctions Default Dataset (1.2 M+ records, streamed)
    # ------------------------------------------------------------------

    def _secure_stream_csv_rows(self, url):
        """Yield CSV rows one at a time from a trusted HTTPS URL.

        Uses requests streaming so the full payload is never buffered in
        memory — safe even for the 300 MB+ default dataset.
        """
        parsed = urlparse(url)
        if parsed.scheme != 'https':
            raise AccessError(_('Blocked non-HTTPS import URL: %s') % url)
        host = (parsed.hostname or '').lower()
        if host not in TRUSTED_IMPORT_HOSTS:
            raise AccessError(_('Blocked untrusted import host: %s') % host)

        response = requests.get(url, timeout=max(self.timeout or 20, 60), stream=True)
        response.raise_for_status()

        # iter_lines() handles chunk boundaries and yields complete decoded lines
        line_iter = response.iter_lines(decode_unicode=True)
        reader = csv.DictReader(line_iter)
        yield from reader

    def _flush_batch(self, batch, source_label):
        """Call _bulk_sql_upsert with retry on transient serialization failures."""
        import time as _time
        from psycopg2.errors import SerializationFailure
        for attempt in range(1, 4):
            try:
                c, u = self._bulk_sql_upsert(batch)
                self.env.cr.commit()
                return c, u
            except SerializationFailure as exc:
                self.env.cr.rollback()
                _logger.warning(
                    '%s: serialization conflict on attempt %s — retrying batch.',
                    source_label, attempt,
                )
                _time.sleep(attempt)
                if attempt == 3:
                    raise

    def _bulk_sql_upsert(self, batch):
        """Single-query batch upsert via PostgreSQL INSERT … ON CONFLICT.

        Processes *batch* (list of value dicts) in one DB round-trip instead
        of 2–3 ORM calls per row.  Returns (created, updated) counts by
        inspecting the xmax system column (0 = freshly inserted row).
        """
        if not batch:
            return 0, 0
        from psycopg2.extras import execute_values

        uid = self.env.uid
        now = fields.Datetime.now()

        # Deduplicate within the batch on the unique key to avoid intra-batch
        # conflicts (the same name can appear more than once in OpenSanctions).
        seen = {}
        for r in batch:
            seen[(r['listed_name'], r['list_source'])] = r

        rows = [
            (
                r['listed_name'],
                r.get('alias_names') or None,
                r['list_source'],
                r.get('listed_type') or 'individual',
                r.get('nationality') or None,
                r.get('un_reference') or None,
                r.get('notes') or None,
                True,       # active
                uid, uid, now, now,
            )
            for r in seen.values()
        ]

        sql = """
            INSERT INTO aml_sanctions_list
                (listed_name, alias_names, list_source, listed_type, nationality,
                 un_reference, notes, active,
                 create_uid, write_uid, create_date, write_date)
            VALUES %s
            ON CONFLICT (listed_name, list_source)
            DO UPDATE SET
                alias_names   = EXCLUDED.alias_names,
                listed_type   = EXCLUDED.listed_type,
                nationality   = EXCLUDED.nationality,
                un_reference  = EXCLUDED.un_reference,
                notes         = EXCLUDED.notes,
                active        = TRUE,
                write_uid     = EXCLUDED.write_uid,
                write_date    = EXCLUDED.write_date
            RETURNING (xmax = 0) AS is_insert
        """
        results = execute_values(self.env.cr._obj, sql, rows, fetch=True)
        created = sum(1 for (is_insert,) in results if is_insert)
        return created, len(results) - created

    def _import_full_dataset_streamed(self, url, source_code, source_label):
        """Stream-import a large targets.simple.csv using batched SQL upserts.

        Accumulates LARGE_IMPORT_BATCH rows then flushes them in a single
        INSERT … ON CONFLICT query (~20× faster than per-row ORM upsert).
        Each batch is committed immediately so no single transaction is large.
        """
        created = updated = processed = 0
        batch = []

        for row in self._secure_stream_csv_rows(url):
            processed += 1
            if processed > LARGE_DATASET_MAX_ROWS:
                _logger.warning(
                    'Large import safety cap (%s rows) hit for %s — stopping.',
                    LARGE_DATASET_MAX_ROWS, source_label,
                )
                break

            name = self._safe_text(row.get('name'), max_len=255)
            if not name:
                continue

            schema = self._safe_text(row.get('schema'), max_len=64).lower()
            if schema in ('organization', 'legalentity', 'company', 'publicbody'):
                listed_type = 'entity'
            elif schema == 'vessel':
                listed_type = 'vessel'
            else:
                listed_type = 'individual'

            batch.append({
                'listed_name': name,
                'alias_names': self._safe_aliases(
                    (row.get('aliases') or '').replace(';', ', ')
                ),
                'list_source': source_code,
                'listed_type': listed_type,
                'nationality': self._safe_text(
                    (row.get('countries') or '').split(';')[0], max_len=128
                ),
                'un_reference': self._safe_text(row.get('id'), max_len=255),
                'notes': self._safe_text(
                    row.get('sanctions') or source_label, max_len=2000
                ),
            })

            if len(batch) >= LARGE_IMPORT_BATCH:
                c, u = self._flush_batch(batch, source_label)
                created += c
                updated += u
                batch = []
                _logger.info(
                    '%s: batch committed — %s records processed so far.',
                    source_label, created + updated,
                )

        # Flush remaining partial batch
        if batch:
            c, u = self._flush_batch(batch, source_label)
            created += c
            updated += u

        return {
            'source': source_label,
            'created': created,
            'updated': updated,
            'total': created + updated,
        }

    def action_schedule_full_dataset_import(self):
        """Queue the full OpenSanctions default dataset import via cron.

        Sets the monthly cron's next-call to now so the Odoo scheduler
        picks it up within its next cycle (usually ≤ 5 minutes).
        Avoids blocking the HTTP request on a 1.2 M-row download.
        """
        self.ensure_one()
        self._assert_manager()

        cron = self.env.ref(
            'aml_compliance.cron_full_sanctions_sync', raise_if_not_found=False
        )
        if cron:
            cron.sudo().write({'nextcall': fields.Datetime.now()})
            msg = _(
                'Full OpenSanctions dataset import (1.2 M+ records) scheduled. '
                'It will run in the background within the next cron cycle.'
            )
        else:
            # Cron not found — run synchronously (e.g. shell/dev)
            _logger.warning('cron_full_sanctions_sync not found — running synchronously.')
            self.cron_sync_full_dataset()
            msg = _('Full dataset import completed synchronously.')

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Full Import Queued'),
                'message': msg,
                'type': 'info',
                'sticky': True,
            },
        }

    @api.model
    def cron_sync_full_dataset(self):
        """Monthly cron: stream the full OpenSanctions default dataset."""
        url = 'https://data.opensanctions.org/datasets/latest/default/targets.simple.csv'
        configs = self.search([('active', '=', True)])
        if not configs:
            _logger.info('No active OpenSanctions config found; skipping full dataset sync.')
            return

        conf = configs[0].sudo()
        _logger.info('Starting full OpenSanctions default dataset import (~1.2 M records)...')
        for attempt in range(1, FULL_IMPORT_MAX_RETRIES + 1):
            try:
                if attempt > 1:
                    _logger.warning(
                        'Retrying full dataset import attempt %s/%s after transient stream error.',
                        attempt,
                        FULL_IMPORT_MAX_RETRIES,
                    )
                result = conf._import_full_dataset_streamed(url, 'opensanctions', 'OpenSanctions Full Dataset')
                summary_line = (
                    f"Full dataset: total={result['total']} "
                    f"(created={result['created']}, updated={result['updated']})"
                )
                _logger.info(summary_line)
                prev_summary = conf.last_sync_summary or ''
                conf.write({
                    'last_sync_at': fields.Datetime.now(),
                    'last_sync_summary': prev_summary + '\n' + summary_line if prev_summary else summary_line,
                    'last_sync_count': (conf.last_sync_count or 0) + result['total'],
                })
                # Final commit for the remaining partial batch
                self.env.cr.commit()
                return
            except (ChunkedEncodingError, RequestException) as exc:
                _logger.warning(
                    'Full dataset import stream interrupted on attempt %s/%s: %s',
                    attempt,
                    FULL_IMPORT_MAX_RETRIES,
                    exc,
                )
                self.env.cr.commit()
                if attempt >= FULL_IMPORT_MAX_RETRIES:
                    _logger.error('Full OpenSanctions dataset import failed after retries: %s', exc, exc_info=True)
                    raise
                import time
                time.sleep(FULL_IMPORT_RETRY_WAIT_SEC)
            except Exception as exc:
                _logger.error('Full OpenSanctions dataset import failed: %s', exc, exc_info=True)
                raise
