# -*- coding: utf-8 -*-
"""
Sanctions Screening Engine

Screens partners against:
  - UN Consolidated Sanctions List
  - UAE Local Terrorist List (National Committee)
  - OFAC SDN List (US — relevant for USD transactions)

Uses fuzzy name matching (Levenshtein ratio) to catch
transliteration variants common in Arabic names.

Screening triggers:
  1. On KYC application submission
  2. On partner create/write (name change)
  3. Periodic batch re-screening (ir.cron)
"""

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import timedelta
import logging

# Minimum pg_trgm similarity (0–1) used in SQL pre-filter.
# 0.3 is permissive enough to catch transliterations yet excludes obvious misses.
_TRGM_THRESHOLD = 0.30
# Final score threshold applied after SQL pre-filter (0–100 scale).
_SCORE_THRESHOLD = 80.0
# Maximum candidates the SQL pre-filter may return per name.
_MAX_CANDIDATES = 50

_logger = logging.getLogger(__name__)


class SanctionsList(models.Model):
    """Sanctions list entry — imported from CSV/XML or API"""

    _name = 'aml.sanctions.list'
    _description = 'Sanctions List Entry'
    _rec_name = 'listed_name'
    _order = 'list_source, listed_name'

    listed_name = fields.Char(
        string='Listed Name',
        required=True,
        index=True,
    )

    alias_names = fields.Text(
        string='Alias Names',
        help='Comma-separated aliases',
    )

    list_source = fields.Selection([
        ('un', 'UN Consolidated List'),
        ('uae_local', 'UAE Local Terrorist List'),
        ('ofac', 'OFAC SDN List'),
        ('eu', 'EU Sanctions List'),
        ('opensanctions', 'OpenSanctions Full Dataset'),
        ('custom', 'Custom / Internal'),
    ], string='List Source', required=True, index=True)

    listed_type = fields.Selection([
        ('individual', 'Individual'),
        ('entity', 'Entity'),
        ('vessel', 'Vessel'),
    ], string='Listed Type', default='individual')

    nationality = fields.Char(string='Nationality')
    date_of_birth = fields.Date(string='Date of Birth')
    passport_number = fields.Char(string='Passport Number')
    national_id = fields.Char(string='National ID')

    listing_date = fields.Date(string='Listing Date')
    delisting_date = fields.Date(string='Delisting Date')
    active = fields.Boolean(default=True)

    un_reference = fields.Char(string='UN Reference')
    notes = fields.Text(string='Notes')

    _name_source_uniq = models.Constraint(
        'UNIQUE(listed_name, list_source)',
        'Duplicate entry for this name and list source.',
    )


class ScreeningResult(models.Model):
    """Result of screening a partner against sanctions lists"""

    _name = 'aml.screening.result'
    _description = 'Sanctions Screening Result'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'screening_date desc'

    name = fields.Char(
        string='Screening Reference',
        required=True,
        readonly=True,
        default='New',
        copy=False,
    )

    state = fields.Selection([
        ('pending', 'Pending Review'),
        ('match', 'Confirmed Match'),
        ('false_positive', 'False Positive'),
        ('cleared', 'Cleared'),
    ], string='Status', default='pending', tracking=True, index=True)

    partner_id = fields.Many2one(
        'res.partner',
        string='Screened Partner',
        required=True,
        ondelete='restrict',
        tracking=True,
    )

    screening_date = fields.Datetime(
        string='Screening Date',
        default=fields.Datetime.now,
        required=True,
    )

    screening_type = fields.Selection([
        ('onboarding', 'Onboarding'),
        ('periodic', 'Periodic Re-screening'),
        ('name_change', 'Name Change'),
        ('manual', 'Manual'),
    ], string='Screening Type', default='manual')

    # --- Match Details ---
    sanctions_entry_id = fields.Many2one(
        'aml.sanctions.list',
        string='Matched Sanctions Entry',
        ondelete='set null',
    )

    match_score = fields.Float(
        string='Match Score (%)',
        help='Fuzzy match score — 100 = exact match',
    )

    matched_name = fields.Char(
        string='Matched Name',
        help='The name from the sanctions list that was matched',
    )

    match_source = fields.Selection(
        related='sanctions_entry_id.list_source',
        string='List Source',
        store=True,
    )

    # --- Resolution ---
    reviewed_by_id = fields.Many2one(
        'res.users',
        string='Reviewed By',
        tracking=True,
    )

    review_date = fields.Datetime(string='Review Date')
    review_notes = fields.Text(string='Review Notes')

    # --- Audit Trail ---
    screened_by_id = fields.Many2one(
        'res.users',
        string='Screened By',
        readonly=True,
        tracking=True,
        help='User who initiated the screening',
    )

    lists_screened = fields.Char(
        string='Lists Screened',
        readonly=True,
        help='Which list sources were checked during this screening run',
    )

    company_id = fields.Many2one(
        'res.company',
        default=lambda self: self.env.company,
        required=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'aml.screening.result'
                ) or 'New'
        return super().create(vals_list)

    # -------------------------------------------------------
    # WORKFLOW
    # -------------------------------------------------------

    def action_confirm_match(self):
        for rec in self:
            rec.write({
                'state': 'match',
                'reviewed_by_id': self.env.uid,
                'review_date': fields.Datetime.now(),
            })
            # Block the partner — sudo() needed since AML officers may not
            # have general res.partner write access
            rec.partner_id.sudo().write({
                'aml_sanctions_match': True,
            })
            rec.message_post(
                body=_('CONFIRMED MATCH — Partner flagged as sanctioned.'),
                message_type='notification',
            )

    def action_false_positive(self):
        for rec in self:
            if not rec.review_notes:
                raise UserError(_('Review notes are required to mark as false positive.'))
            rec.write({
                'state': 'false_positive',
                'reviewed_by_id': self.env.uid,
                'review_date': fields.Datetime.now(),
            })

    def action_clear(self):
        for rec in self:
            rec.write({
                'state': 'cleared',
                'reviewed_by_id': self.env.uid,
                'review_date': fields.Datetime.now(),
            })

    # -------------------------------------------------------
    # SCREENING ENGINE
    # -------------------------------------------------------

    @api.model
    def quick_screen_partner(self, partner_name):
        """Fast, read-only sanctions check given a plain name string.

        Uses the GIN trigram index for a sub-millisecond SQL pre-filter
        then applies the Levenshtein score to each candidate.

        Returns a list of dicts::

            [
                {
                    'id': <sanctions entry id>,
                    'listed_name': '...',
                    'list_source': '...',
                    'listed_type': '...',
                    'score': 95.0,       # 0-100
                    'matched_via': 'name' | 'alias',
                },
                ...
            ]

        Typical call time: < 5 ms even against 1.2 M entries.
        """
        name = (partner_name or '').strip()
        if not name:
            return []
        return self._local_fuzzy_sql(name)

    @api.model
    def _local_fuzzy_sql(self, name, threshold=None, limit=None):
        """SQL-backed fuzzy match using pg_trgm similarity index.

        Two-pass approach:
          1. Fast GIN trigram pre-filter (set_limit + similarity operator %) —
             uses the index, returns O(candidates) not O(table).
          2. Python Levenshtein re-score on the small candidate set for
             precision (pg_trgm measures n-gram overlap, not edit distance).
        """
        threshold = threshold if threshold is not None else _TRGM_THRESHOLD
        limit = limit if limit is not None else _MAX_CANDIDATES
        score_min = _SCORE_THRESHOLD

        cr = self.env.cr
        # set_limit is session-local; safe to call before the query.
        cr.execute("SELECT set_limit(%s)", (threshold,))

        cr.execute("""
            SELECT
                sl.id,
                sl.listed_name,
                sl.alias_names,
                sl.list_source,
                sl.listed_type,
                similarity(sl.listed_name, %s) AS trgm_score
            FROM aml_sanctions_list sl
            WHERE sl.active = TRUE
              AND sl.listed_name %% %s
            ORDER BY trgm_score DESC
            LIMIT %s
        """, (name, name, limit))
        rows = cr.fetchall()

        name_lower = name.lower()
        hits = []
        for (eid, ename, aliases, source, etype, _trgm) in rows:
            score = self._fuzzy_match(name_lower, (ename or '').lower())
            if score >= score_min:
                hits.append({
                    'id': eid,
                    'listed_name': ename,
                    'list_source': source,
                    'listed_type': etype,
                    'score': score,
                    'matched_via': 'name',
                })
                continue
            # Check aliases from the already-fetched row (no extra DB query)
            if aliases:
                for alias in aliases.split(','):
                    alias_s = alias.strip().lower()
                    if not alias_s:
                        continue
                    alias_score = self._fuzzy_match(name_lower, alias_s)
                    if alias_score >= score_min:
                        hits.append({
                            'id': eid,
                            'listed_name': ename,
                            'list_source': source,
                            'listed_type': etype,
                            'score': alias_score,
                            'matched_via': 'alias',
                        })
                        break

        hits.sort(key=lambda h: h['score'], reverse=True)
        return hits

    @api.model
    def _aml_compliance_users(self):
        """Users to alert on a sanctions hit: MLRO, else AML Manager, else AML Officer."""
        for xmlid in ('aml_compliance.group_mlro', 'aml_compliance.group_aml_manager',
                      'aml_compliance.group_aml_officer'):
            group = self.env.ref(xmlid, raise_if_not_found=False)
            if not group:
                continue
            users = (group.all_user_ids if 'all_user_ids' in group._fields
                     else group.user_ids).filtered(lambda u: u.active)
            if users:
                return users
        return self.env['res.users']

    def screen_partner(self, partner, screening_type='manual'):
        """Screen a single partner against sanctions lists.

        Strategy:
        1. Query the self-hosted yente / OpenSanctions API (if configured + reachable).
        2. Fall back to local fuzzy matching against ``aml.sanctions.list`` if yente
           is disabled, unreachable, or returns no entries.

        An audit record is ALWAYS created (even for cleared results) so that every
        screening action has an immutable timestamped log entry.

        Returns: recordset of created ``aml.screening.result`` records.
        """
        if not partner:
            return self.env['aml.screening.result']

        results = self.env['aml.screening.result']
        screened_by = self.env.uid
        now = fields.Datetime.now()

        # ------------------------------------------------------------------
        # STEP 1 — Try OpenSanctions API (POST /match — structured FtM query)
        # ------------------------------------------------------------------
        api_hit = False
        lists_used = []
        config = False
        if self.env.registry.models.get('aml.opensanctions.config'):
            config = self.env['aml.opensanctions.config'].get_config()
        else:
            _logger.info(
                'OpenSanctions config model is not installed; using local sanctions fallback only.'
            )

        if config:
            api_results = config.match_partner(partner)
            lists_used.append('OpenSanctions API')
            for hit in api_results:
                score_pct = round(hit.get('score', 0) * 100, 1)
                entry = config._upsert_sanctions_entry(hit)
                results |= self._create_screening_result(
                    partner, entry, score_pct,
                    hit.get('caption', entry.listed_name),
                    screening_type, screened_by, now, 'OpenSanctions API',
                )
                api_hit = True

        # ------------------------------------------------------------------
        # STEP 2 — Local fuzzy fallback using GIN trigram SQL index
        # Fast even against 1.2 M entries: index pre-filter + small Levenshtein
        # pass on candidates only (typically <50 rows touched per query).
        # ------------------------------------------------------------------
        if not api_hit:
            # Quick count to build the label (cheap — uses index scan)
            total_local = self.env['aml.sanctions.list'].search_count(
                [('active', '=', True)]
            )
            if total_local:
                partner_name = (partner.name or '').strip()
                hits = self._local_fuzzy_sql(partner_name)

                # Collect distinct sources from the candidate rows
                src_set = {h['list_source'] for h in hits}
                if not src_set:
                    # Still need a source label even when nothing matched
                    self.env.cr.execute(
                        "SELECT DISTINCT list_source FROM aml_sanctions_list "
                        "WHERE active=TRUE LIMIT 10"
                    )
                    src_set = {r[0] for r in self.env.cr.fetchall()}

                src_names = ', '.join(sorted(src_set)) or 'Local DB'
                lists_used.append(
                    f'Local DB ({total_local:,} entries screened — {src_names})'
                )

                sl_model = self.env['aml.sanctions.list']
                for h in hits:
                    entry = sl_model.browse(h['id'])
                    matched_label = (
                        h['listed_name'] if h['matched_via'] == 'name'
                        else f"{h['listed_name']} (alias)"
                    )
                    results |= self._create_screening_result(
                        partner, entry, h['score'], matched_label,
                        screening_type, screened_by, now, src_names,
                    )
            else:
                _logger.info('No active sanctions list entries to screen against.')
                lists_used.append('Local DB (empty)')

        lists_label = '; '.join(lists_used) if lists_used else 'None'

        # ------------------------------------------------------------------
        # Always create a cleared audit record when no matches found
        # ------------------------------------------------------------------
        if not results:
            _logger.info('Partner %s cleared — no sanctions matches.', partner.name)
            cleared_rec = self.create({
                'partner_id': partner.id,
                'screening_type': screening_type,
                'state': 'cleared',
                'screened_by_id': screened_by,
                'lists_screened': lists_label,
                'review_date': now,
                'reviewed_by_id': screened_by,
                'review_notes': _('Automated: no matches found — partner cleared.'),
            })
            results = cleared_rec
        else:
            # Stamp all match records with audit fields
            results.write({
                'screened_by_id': screened_by,
                'lists_screened': lists_label,
            })

        partner.sudo().write({
            'aml_last_screening_date': now,
            'aml_sanctions_match': bool(
                results.filtered(lambda r: r.state not in ('cleared', 'false_positive'))
            ),
        })

        # Flag to the CMO / MLRO: create a to-do activity for every compliance
        # user (MLRO, else AML Manager, else AML Officer) so a hit is never
        # silently buried in the partner chatter.
        pending_hits = results.filtered(lambda r: r.state == 'pending')
        if pending_hits:
            stale = partner.activity_ids.filtered(
                lambda a: a.summary and a.summary.startswith('AML sanctions hit'))
            stale.unlink()
            names = ', '.join(pending_hits.mapped('matched_name')[:5])
            summary = _('AML sanctions hit: %s', partner.display_name)
            note = _('%(n)s match(es) against: %(names)s. Review in AML > Sanctions Screening.',
                     n=len(pending_hits), names=names)
            for user in self._aml_compliance_users():
                partner.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=user.id,
                    summary=summary, note=note)

        # Post chatter message on the partner for full audit visibility
        partner.sudo().message_post(
            body=_(
                '<b>Sanctions Screening Run</b><br/>'
                'Type: %(type)s | Lists: %(lists)s | Result: %(result)s | By: %(user)s',
                type=screening_type,
                lists=lists_label,
                result='MATCH FOUND' if any(
                    r.state == 'pending' for r in results
                ) else 'CLEARED',
                user=self.env.user.name,
            ),
            message_type='notification',
        )

        return results

    def _create_screening_result(self, partner, entry, score, matched_name,
                                 screening_type, screened_by=None, screening_date=None,
                                 lists_screened=None):
        """Create a screening result record with full audit fields."""
        vals = {
            'partner_id': partner.id,
            'sanctions_entry_id': entry.id,
            'match_score': score,
            'matched_name': matched_name,
            'screening_type': screening_type,
        }
        if screened_by:
            vals['screened_by_id'] = screened_by
        if screening_date:
            vals['screening_date'] = screening_date
        if lists_screened:
            vals['lists_screened'] = lists_screened
        return self.create(vals)

    @staticmethod
    def _fuzzy_match(s1, s2):
        """Simple Levenshtein-based similarity ratio (0-100).
        No external deps — pure Python implementation.
        """
        if not s1 or not s2:
            return 0.0
        if s1 == s2:
            return 100.0

        len1, len2 = len(s1), len(s2)
        # Quick length check — if lengths differ too much, skip
        if abs(len1 - len2) > max(len1, len2) * 0.5:
            return 0.0

        # Levenshtein distance (Wagner-Fischer)
        matrix = [[0] * (len2 + 1) for _ in range(len1 + 1)]
        for i in range(len1 + 1):
            matrix[i][0] = i
        for j in range(len2 + 1):
            matrix[0][j] = j
        for i in range(1, len1 + 1):
            for j in range(1, len2 + 1):
                cost = 0 if s1[i - 1] == s2[j - 1] else 1
                matrix[i][j] = min(
                    matrix[i - 1][j] + 1,
                    matrix[i][j - 1] + 1,
                    matrix[i - 1][j - 1] + cost,
                )
        distance = matrix[len1][len2]
        max_len = max(len1, len2)
        return round((1 - distance / max_len) * 100, 1)

    @api.model
    def run_batch_screening(self):
        """Scheduled action: re-screen all active customer partners.

        Uses offset-based pagination with a mid-batch commit so a large
        partner list does not produce a single huge transaction.
        """
        _logger.info('AML Batch Sanctions Screening: starting...')
        CHUNK = 200
        offset = 0
        total_matches = 0
        total_partners = 0

        while True:
            partners = self.env['res.partner'].search(
                [('customer_rank', '>', 0), ('active', '=', True)],
                limit=CHUNK,
                offset=offset,
            )
            if not partners:
                break
            for partner in partners:
                results = self.screen_partner(partner, screening_type='periodic')
                total_matches += sum(
                    1 for r in results if r.state == 'pending'
                )
            total_partners += len(partners)
            offset += CHUNK
            # Commit each chunk so no single transaction spans millions of rows
            self.env.cr.commit()
            _logger.info(
                'AML Batch Screening: %d partners processed so far, %d pending matches.',
                total_partners, total_matches,
            )

        _logger.info(
            'AML Batch Screening complete: %d partners screened, %d pending matches.',
            total_partners, total_matches,
        )
        return total_matches
