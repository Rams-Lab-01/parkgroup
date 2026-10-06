# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Escrow configuration and ledger roll-ups on ``property.project``.

One project == one escrow bank account == one escrow journal. That mirrors UAE
practice: the escrow account is registered with DLD per project, and withdrawals
are only permitted against certified construction progress.

Everything financial here is a *query* over ``account.move.line``. There is no
escrow subledger to reconcile, because the general ledger already is one.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# Progress fields whose change can move money out of escrow. Attested in the
# critical-audit chain (see sgc.critical.audit.mixin, Entry 28 convention).
_ESCROW_PROJECT_WATCHED = frozenset({
    'escrow_enabled',
    'escrow_bank_journal_id',
    'escrow_release_journal_id',
    'escrow_agent_id',
    'escrow_account_ref',
    'escrow_retention_pct',
    'escrow_certified_progress',
    'escrow_certified_date',
    'escrow_certified_by',
})


class PropertyProjectEscrow(models.Model):
    _inherit = 'property.project'

    _audit_watched_fields = _ESCROW_PROJECT_WATCHED

    # -- A. Escrow configuration ---
    escrow_enabled = fields.Boolean(
        string='Escrow Enabled',
        default=False,
        tracking=True,
        help='Turn on only once the real escrow bank account for this project has '
             'been opened and registered with the DLD / RERA. While off, no '
             'entitlement is computed and no release can be created.',
    )
    escrow_bank_journal_id = fields.Many2one(
        'account.journal',
        string='Escrow Bank Journal',
        domain="[('type', '=', 'bank'), ('company_id', '=', allowed_company_ids)]",
        check_company=True,
        tracking=True,
        help='The project escrow bank account. Buyer receipts for this project are '
             'expected to land here.',
    )
    escrow_release_journal_id = fields.Many2one(
        'account.journal',
        string='Operating Bank Journal',
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', allowed_company_ids)]",
        check_company=True,
        help='Where released money is transferred to. Leave empty to fall back to '
             'the company default bank journal.',
    )
    escrow_account_id = fields.Many2one(
        'account.account',
        string='Escrow Ledger Account',
        related='escrow_bank_journal_id.default_account_id',
        store=True,
        readonly=True,
        help='Technical field: the GL account backing the escrow bank journal. All '
             'escrow roll-ups are filtered on this account.',
    )
    escrow_agent_id = fields.Many2one(
        'res.partner',
        string='Escrow Agent / Bank',
        help='The bank or escrow agent holding the project escrow account.',
    )
    escrow_account_ref = fields.Char(
        string='DLD Escrow Account No.',
        tracking=True,
        help='The escrow account number as registered with the Dubai Land '
             'Department (or the relevant emirate authority).',
    )
    escrow_retention_pct = fields.Float(
        string='Retention %',
        digits=(5, 2),
        default=5.0,
        tracking=True,
        help='Percentage of the money certified as due that is retained until '
             'project completion. Typical statutory retention is 5%%.',
    )

    # -- Certified construction progress (the release basis) ---
    escrow_certified_progress = fields.Float(
        string='Certified Progress %',
        digits=(5, 2),
        default=0.0,
        tracking=True,
        help='Percentage of the project certified complete by the engineer / '
             'consultant. Releases are capped by this figure, so it is the single '
             'control that keeps withdrawals inside the escrow account.',
    )
    escrow_certified_date = fields.Date(
        string='Certified On',
        tracking=True,
    )
    escrow_certified_by = fields.Many2one(
        'res.partner',
        string='Certified By',
        tracking=True,
        help='The independent engineer or consultant who certified the progress.',
    )
    escrow_progress_source = fields.Selection(
        [
            ('manual', 'Certified Manually'),
            ('phases', 'From Construction Phases'),
        ],
        string='Progress Source',
        default='manual',
        required=True,
        help='"From Construction Phases" becomes available once weighted construction '
             'phases are installed in the Property Management module. Until then the '
             'percentage is certified and entered manually, with the certificate '
             'attached below.',
    )
    escrow_progress_evidence = fields.Binary(
        string='Progress Certificate',
        attachment=True,
        help="The engineer's progress certificate supporting the certified percentage.",
    )
    escrow_progress_evidence_filename = fields.Char(
        string='Progress Certificate File Name',
    )

    # -- Ledger roll-ups (money in) ---
    escrow_received_amount = fields.Monetary(
        string='Received into Escrow',
        currency_field='escrow_currency_id',
        compute='_compute_escrow_ledger_totals',
        help='Sum of posted ledger lines on the escrow bank account.',
    )
    escrow_released_amount = fields.Monetary(
        string='Released from Escrow',
        currency_field='escrow_currency_id',
        compute='_compute_escrow_ledger_totals',
        help='Sum of posted escrow-release entries out of the escrow bank account.',
    )
    escrow_balance_amount = fields.Monetary(
        string='Escrow Balance',
        currency_field='escrow_currency_id',
        compute='_compute_escrow_ledger_totals',
        help='Money still held in the escrow bank account.',
    )

    # -- Entitlement roll-ups (money out may not exceed these) ---
    escrow_entitled_amount = fields.Monetary(
        string='Entitled (Cumulative)',
        currency_field='escrow_currency_id',
        compute='_compute_escrow_entitlement',
        help='received x certified progress% x (1 - retention%). The cumulative '
             'ceiling of what may ever be released for this project.',
    )
    escrow_releasable_amount = fields.Monetary(
        string='Releasable Now',
        currency_field='escrow_currency_id',
        compute='_compute_escrow_entitlement',
        help='Entitled (cumulative) less everything already released. This is the '
             'amount a new release document may draw.',
    )

    # -- Allocation register roll-ups ---
    escrow_allocation_ids = fields.One2many(
        'escrow.allocation',
        'project_id',
        string='Escrow Allocations',
    )
    escrow_allocation_count = fields.Integer(
        string='Units Tracked',
        compute='_compute_escrow_allocation_totals',
    )
    escrow_allocation_pending_count = fields.Integer(
        string='Awaiting Source Data',
        compute='_compute_escrow_allocation_totals',
        help='Units where the source carried no escrow allocation figure yet.',
    )
    escrow_allocation_flag_count = fields.Integer(
        string='Flagged',
        compute='_compute_escrow_allocation_totals',
        help='Units with an open reconciliation flag awaiting finance sign-off.',
    )
    escrow_allocation_required_amount = fields.Monetary(
        string='Required by Rules',
        currency_field='escrow_currency_id',
        compute='_compute_escrow_allocation_totals',
    )
    escrow_allocation_allocated_amount = fields.Monetary(
        string='Allocated per Source',
        currency_field='escrow_currency_id',
        compute='_compute_escrow_allocation_totals',
    )
    escrow_allocation_variance_amount = fields.Monetary(
        string='Allocation Variance',
        currency_field='escrow_currency_id',
        compute='_compute_escrow_allocation_totals',
        help='Allocated per source less required by rules, across all tracked units.',
    )

    # -- Release register roll-ups ---
    escrow_release_ids = fields.One2many(
        'escrow.release',
        'project_id',
        string='Escrow Releases',
    )
    escrow_release_count = fields.Integer(
        string='Releases',
        compute='_compute_escrow_release_totals',
    )
    escrow_release_pending_count = fields.Integer(
        string='Awaiting Approval',
        compute='_compute_escrow_release_totals',
    )

    escrow_currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        compute='_compute_currency_id',
        readonly=True,
    )

    # -- Constraints ---
    @api.constrains('escrow_retention_pct')
    def _check_escrow_retention_pct(self):
        for record in self:
            if record.escrow_retention_pct < 0.0 or record.escrow_retention_pct > 100.0:
                raise ValidationError(_(
                    'Retention %% must be between 0 and 100 (%s has %.2f).'
                ) % (record.code or record.name, record.escrow_retention_pct))

    @api.constrains('escrow_certified_progress')
    def _check_escrow_certified_progress(self):
        for record in self:
            if record.escrow_certified_progress < 0.0 or record.escrow_certified_progress > 100.0:
                raise ValidationError(_(
                    'Certified progress %% must be between 0 and 100 (%s has %.2f).'
                ) % (record.code or record.name, record.escrow_certified_progress))

    @api.constrains('escrow_enabled', 'escrow_bank_journal_id')
    def _check_escrow_enabled_has_journal(self):
        for record in self:
            if record.escrow_enabled and not record.escrow_bank_journal_id:
                raise ValidationError(_(
                    'Cannot enable escrow for %s without an escrow bank journal. '
                    'Create or select the project escrow bank account first.'
                ) % (record.code or record.name))

    @api.constrains('escrow_bank_journal_id')
    def _check_escrow_journal_not_shared(self):
        for record in self:
            journal = record.escrow_bank_journal_id
            if journal and record.id:
                clash = self.search([
                    ('id', '!=', record.id),
                    ('escrow_bank_journal_id', '=', journal.id),
                ], limit=1)
                if clash:
                    raise ValidationError(_(
                        'Journal %(journal)s is already the escrow journal of project '
                        '%(other)s. One escrow account belongs to exactly one project.'
                    ) % {
                        'journal': journal.display_name,
                        'other': clash.code or clash.name,
                    })

    # -- Computes ---
    def _compute_currency_id(self):
        """Company currency, deliberately.

        Every escrow roll-up is ``SUM(account.move.line.balance)``, and ``balance``
        is denominated in ``company_currency_id`` -- not in the journal's own
        currency. Labelling these Monetary fields with the journal currency would
        misstate the figures whenever the two differ, so the label is pinned to
        the company currency and multi-currency escrow accounts are out of scope
        by design (see README section 9).
        """
        for record in self:
            record.escrow_currency_id = (
                record.company_id.currency_id
                or self.env.company.currency_id
            )

    def _escrow_ledger_domain(self, release_only=False):
        """Domain selecting posted lines on this project's escrow bank account.

        ``release_only`` selects the movements of posted escrow-release
        documents AND their reversals, so a reversed release nets to zero --
        the money is back in escrow and must stop counting as spent.
        """
        self.ensure_one()
        domain = [
            ('account_id', '=', self.escrow_account_id.id),
            ('parent_state', '=', 'posted'),
            ('company_id', '=', self.company_id.id),
        ]
        if release_only:
            domain += [
                '|',
                ('move_id.escrow_release_id', '!=', False),
                ('move_id.reversed_entry_id.escrow_release_id', '!=', False),
            ]
        return domain

    def _escrow_balance_sum(self, domain):
        """Sum of ``balance`` over ``domain``, in COMPANY currency.

        ``account.move.line.balance`` is expressed in ``company_currency_id``,
        never in the journal's own currency -- which is why ``escrow_currency_id``
        is pinned to the company currency. The empty-result guard matters: this
        runs on every project form read, and an IndexError here would take the
        form down rather than show a zero.
        """
        rows = self.env['account.move.line']._read_group(
            domain, [], ['balance:sum'],
        )
        return rows[0][0] if rows else 0.0

    def _escrow_ledger_totals(self):
        """Return (received, released, balance) straight from the ledger.

        ``received`` is cumulative INFLOW: positive posted lines on the escrow
        account, excluding reversal entries. Outflows never reduce it -- a
        manual correction out of escrow shrinks the balance but leaves the
        money that was collected (and the entitlement built on it) intact.

        ``released`` is the net movement of posted escrow-release documents
        (and their reversals), returned as a positive number: what the
        authorisations have taken out of escrow and not yet given back.

        ``balance`` is the signed sum of every posted line -- what the bank
        statement should show.
        """
        self.ensure_one()
        if not self.escrow_account_id:
            return 0.0, 0.0, 0.0
        domain = self._escrow_ledger_domain()
        balance = self._escrow_balance_sum(domain)
        received = self._escrow_balance_sum(
            domain + [
                ('balance', '>', 0),
                ('move_id.reversed_entry_id', '=', False),
            ])
        released_signed = self._escrow_balance_sum(
            self._escrow_ledger_domain(release_only=True))
        return received, -released_signed, balance

    @api.depends(
        'escrow_enabled', 'escrow_account_id', 'escrow_bank_journal_id',
        'company_id', 'escrow_currency_id',
    )
    def _compute_escrow_ledger_totals(self):
        for record in self:
            received, released, balance = record._escrow_ledger_totals()
            record.escrow_received_amount = received
            record.escrow_released_amount = released
            record.escrow_balance_amount = balance

    @api.depends(
        'escrow_enabled', 'escrow_account_id', 'escrow_retention_pct',
        'escrow_certified_progress', 'escrow_currency_id', 'company_id',
        'escrow_bank_journal_id',
    )
    def _compute_escrow_entitlement(self):
        for record in self:
            if not record.escrow_enabled:
                record.escrow_entitled_amount = 0.0
                record.escrow_releasable_amount = 0.0
                continue
            received, released, _balance = record._escrow_ledger_totals()
            entitled = received * (record.escrow_certified_progress / 100.0)
            entitled *= (1.0 - (record.escrow_retention_pct / 100.0))
            record.escrow_entitled_amount = entitled
            record.escrow_releasable_amount = max(0.0, entitled - released)

    @api.depends(
        'escrow_allocation_ids.allocated_amount',
        'escrow_allocation_ids.sale_price_snapshot',
        'escrow_allocation_ids.escrow_pct',
        'escrow_allocation_ids.has_source_data',
        'escrow_allocation_ids.flag_code',
    )
    def _compute_escrow_allocation_totals(self):
        for record in self:
            allocations = record.escrow_allocation_ids
            record.escrow_allocation_count = len(allocations)
            record.escrow_allocation_pending_count = len(
                allocations.filtered(lambda a: not a.has_source_data))
            record.escrow_allocation_flag_count = len(
                allocations.filtered(lambda a: bool(a.flag_code)))
            record.escrow_allocation_required_amount = sum(
                allocations.mapped('required_amount'))
            record.escrow_allocation_allocated_amount = sum(
                allocations.mapped('allocated_amount'))
            record.escrow_allocation_variance_amount = sum(
                allocations.mapped('variance_amount'))

    @api.depends('escrow_release_ids.state')
    def _compute_escrow_release_totals(self):
        for record in self:
            releases = record.escrow_release_ids
            record.escrow_release_count = len(releases)
            record.escrow_release_pending_count = len(releases.filtered(
                lambda r: r.state == 'draft'))

    # -- Setup helper ---
    def action_setup_escrow_journal(self):
        """Create the project's escrow bank journal from the bank account details.

        Deliberately a separate, explicit action: creating financial records is a
        conscious act, never a side effect of enabling the checkbox.
        """
        self.ensure_one()
        if self.escrow_bank_journal_id:
            raise ValidationError(_(
                'Project %s already has escrow bank journal %s.'
            ) % (self.display_name, self.escrow_bank_journal_id.display_name))

        company = self.company_id or self.env.company
        agent = self.escrow_agent_id or company.partner_id
        account_ref = self.escrow_account_ref or 'PENDING'

        journal = self.env['account.journal'].create({
            'name': _('%(project)s Escrow Account') % {'project': self.code or self.name},
            'code': self._escrow_journal_code(),
            'type': 'bank',
            'company_id': company.id,
            'bank_account_id': self._escrow_partner_bank(agent, account_ref).id,
        })
        # Odoo 19 posts a payment's liquidity line through the payment-method
        # line's outstanding account (payment_account_id), never directly on
        # journal.default_account_id -- money only reaches the journal's bank
        # account through statement reconciliation. The escrow roll-ups read
        # lines on the escrow account itself, so point the method lines there:
        # receipts must count as received the moment they are posted, not weeks
        # later when the bank statement lands.
        (journal.inbound_payment_method_line_ids
         | journal.outbound_payment_method_line_ids).write({
            'payment_account_id': journal.default_account_id.id,
        })
        self.escrow_bank_journal_id = journal
        self.escrow_enabled = True
        return {
            'type': 'ir.actions.act_window',
            'name': _('Escrow Bank Account'),
            'res_model': 'account.journal',
            'view_mode': 'form',
            'res_id': journal.id,
        }

    def _escrow_journal_code(self):
        """Deterministic 5-char journal code derived from the project code."""
        base = ''.join(ch for ch in (self.code or 'ESCR') if ch.isalnum()).upper()
        base = (base + 'ESCR')[:5]
        existing = set(self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id),
        ]).mapped('code'))
        if base not in existing:
            return base
        for suffix in '23456789':
            candidate = (base[:4] + suffix)
            if candidate not in existing:
                return candidate
        raise ValidationError(_(
            'Could not derive a free journal code for project %s. Create the bank '
            'journal manually.'
        ) % (self.code or self.name))

    def _escrow_partner_bank(self, agent, account_ref):
        """Find or create the escrow agent's bank account for this project."""
        Bank = self.env['res.partner.bank']
        existing = Bank.search([
            ('partner_id', '=', agent.id),
            ('acc_number', '=', account_ref),
        ], limit=1)
        if existing:
            return existing
        return Bank.create({
            'acc_number': account_ref,
            'partner_id': agent.id,
            'company_id': self.company_id.id,
        })

    # -- Navigation actions ---
    def action_view_escrow_releases(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Escrow Releases'),
            'res_model': 'escrow.release',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_escrow_allocations(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Escrow Allocations'),
            'res_model': 'escrow.allocation',
            'view_mode': 'list,form',
            'domain': [('project_id', '=', self.id)],
            'context': {'default_project_id': self.id},
        }

    def action_view_escrow_ledger(self):
        """Open the raw escrow bank ledger so the roll-ups can be audited."""
        self.ensure_one()
        action = self.env.ref('account.action_account_moves_all', raise_if_not_found=False)
        if not action:
            action = self.env.ref('account.action_account_moves_all_grouped_movements',
                                   raise_if_not_found=False)
        domain = [('account_id', '=', self.escrow_account_id.id), ('parent_state', '=', 'posted')]
        if action:
            action = action.read()[0]
            action['domain'] = domain
            action['context'] = {'search_default_account_id': self.escrow_account_id.id}
            action['name'] = _('Escrow Bank Ledger - %s') % (self.code or self.name)
        else:
            action = {
                'type': 'ir.actions.act_window',
                'name': _('Escrow Bank Ledger - %s') % (self.code or self.name),
                'res_model': 'account.move.line',
                'view_mode': 'list',
                'domain': domain,
            }
        return action
