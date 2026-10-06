# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""escrow.release -- the progress-gated withdrawal document.

This is the only thing in the system allowed to move money out of a project
escrow account, and it is deliberately hard to misuse.

The entitlement ceiling (cumulative, snapshot-based)::

    entitled_cumulative = received_total x (certified_progress / 100)
                                        x (1 - retention_pct / 100)
    releasable_now      = max(0, entitled_cumulative - released_total)

``received_total`` is read from the ledger, ``released_total`` counts only
previously posted releases, and every input is *snapshotted* into the document
on creation. The snapshots are what makes the document defensible months later:
an auditor reads the figures the release was authorised against, not whatever
the project looks like today.

Approval discipline
---
Draft -> approved freezes the figures. Posting writes exactly one journal entry
(Dr operating bank / Cr escrow bank -- a transfer of own funds, no P&L effect,
exactly as the bank executes it). A posted release is reversed, never deleted or
cancelled, so the escrow history stays append-only.
"""

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

_ESCROW_RELEASE_WATCHED = frozenset({
    'project_id',
    'date',
    'amount',
    'state',
    'is_override',
    'override_reason',
    'journal_entry_id',
})

# Context flag that lifts the direct-write guard for the module's own actions.
_CONTROLLED_WRITE_KEY = 'sgc_escrow_controlled_write'


class EscrowRelease(models.Model):
    """Authorised, progress-gated withdrawal from a project escrow account."""

    _name = 'escrow.release'
    _description = 'Escrow Release (Construction Progress Withdrawal)'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _order = 'date desc, id desc'

    # Releases are corrected by reversal, so destructive unlink stays reason-gated.
    _audit_unlink_requires_reason = True
    _audit_watched_fields = _ESCROW_RELEASE_WATCHED

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )

    # -- Header ---
    project_id = fields.Many2one(
        'property.project',
        string='Project',
        required=True,
        ondelete='restrict',
        index=True,
        tracking=True,
        readonly=True,
    )
    date = fields.Date(
        string='Release Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    operating_journal_id = fields.Many2one(
        'account.journal',
        string='Operating Bank Journal',
        required=True,
        check_company=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', allowed_company_ids)]",
        help='Bank/cash journal that receives the released money.',
    )
    payment_reference = fields.Char(
        string='Bank / RERA Reference',
        help='Approval or transaction reference from the escrow bank or RERA.',
    )
    notes = fields.Text(string='Notes')

    # -- Certification basis (snapshotted) ---
    certified_progress_snapshot = fields.Float(
        string='Certified Progress % (snapshot)',
        digits=(5, 2),
        readonly=True,
    )
    retention_pct_snapshot = fields.Float(
        string='Retention % (snapshot)',
        digits=(5, 2),
        readonly=True,
    )
    certified_by_snapshot = fields.Many2one(
        'res.partner',
        string='Certified By (snapshot)',
        readonly=True,
    )
    certified_date_snapshot = fields.Date(
        string='Certified On (snapshot)',
        readonly=True,
    )
    progress_evidence = fields.Binary(
        string='Progress Certificate',
        attachment=True,
        help="The engineer's progress certificate supporting this release.",
    )
    progress_evidence_filename = fields.Char(
        string='Progress Certificate File Name',
    )

    # -- Ledger basis (snapshotted) ---
    received_snapshot = fields.Monetary(
        string='Received into Escrow (snapshot)',
        currency_field='currency_id',
        readonly=True,
    )
    released_before_snapshot = fields.Monetary(
        string='Released Before (snapshot)',
        currency_field='currency_id',
        readonly=True,
    )
    entitled_snapshot = fields.Monetary(
        string='Entitled Cumulative (snapshot)',
        currency_field='currency_id',
        readonly=True,
    )
    releasable_snapshot = fields.Monetary(
        string='Releasable Now (snapshot)',
        currency_field='currency_id',
        readonly=True,
        help='What this document was allowed to draw at the moment it was drafted.',
    )

    # -- The money ---
    # Per-state readonly is enforced in the form view, not with the `states=`
    # field attribute: `states` was removed in Odoo 17 and is now only a log
    # warning, which would leave these three fields locked forever.
    # See views/escrow_release_views.xml for the per-state control.
    amount = fields.Monetary(
        string='Release Amount',
        currency_field='currency_id',
        required=True,
        tracking=True,
    )
    amount_exceeds_entitlement = fields.Boolean(
        string='Exceeds Entitlement',
        compute='_compute_amount_exceeds_entitlement',
        help='The requested amount is above what certified progress allows.',
    )
    remaining_after_release = fields.Monetary(
        string='Releasable After This',
        currency_field='currency_id',
        compute='_compute_amount_exceeds_entitlement',
    )

    # -- Override (Escrow Manager only) ---
    is_override = fields.Boolean(
        string='Override Entitlement',
        tracking=True,
        help='Release above the progress-based entitlement. Requires an Escrow '
             'Manager role and a written reason; the override is permanently audited.',
    )
    override_reason = fields.Text(
        string='Override Reason',
    )
    override_user_id = fields.Many2one(
        'res.users',
        string='Override By',
        readonly=True,
        copy=False,
    )

    # -- State ---
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('approved', 'Approved'),
            ('posted', 'Posted'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        copy=False,
        tracking=True,
        index=True,
    )

    journal_entry_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        copy=False,
        readonly=True,
        index=True,
        help='The ledger entry that moved the money out of escrow.',
    )
    reversal_entry_id = fields.Many2one(
        'account.move',
        string='Reversal Entry',
        copy=False,
        readonly=True,
    )
    escrow_line_id = fields.Many2one(
        'account.move.line',
        string='Escrow Account Line',
        copy=False,
        readonly=True,
    )
    operating_line_id = fields.Many2one(
        'account.move.line',
        string='Operating Account Line',
        copy=False,
        readonly=True,
    )

    # -- SQL constraints ---
    # Odoo 19: DB-level constraints are declared as models.Constraint class
    # attributes (the legacy _sql_constraints list is silently ignored).
    _escrow_release_name_uniq = models.Constraint(
        'unique (name)',
        'Escrow release reference must be unique.',
    )

    # -- Lifecycle ---
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # amount is NOT NULL at the SQL level too; 0 lets
            # _refresh_snapshots(default_amount=True) substitute the full
            # releasable figure right after the insert (and an explicit amount
            # passed by callers is written over that default afterwards).
            vals.setdefault('amount', 0.0)
            project = (
                self.env['property.project'].browse(vals['project_id'])
                if vals.get('project_id') else None
            )
            if project and project.company_id:
                vals.setdefault('company_id', project.company_id.id)
            if not vals.get('operating_journal_id'):
                # operating_journal_id is NOT NULL at the SQL level, so the
                # fallback has to be in vals BEFORE super().create() inserts --
                # _refresh_snapshots() runs too late to rescue the row.
                company = (
                    project.company_id
                    if project and project.company_id
                    else self.env['res.company'].browse(vals.get('company_id'))
                    or self.env.company
                )
                vals['operating_journal_id'] = (
                    (project and project.escrow_release_journal_id.id)
                    or self._default_operating_journal_for(company)
                )
            # The reference is assigned BEFORE the INSERT, never after it.
            # The unique index on name is enforced by PostgreSQL at INSERT
            # time, while a post-insert ORM write that renames 'New' stays in
            # the cache until flush -- so renaming after super().create() let
            # the second row of a batch create (or the next create of the same
            # transaction, where nothing had flushed escrow_release yet) collide
            # with the first on 'New'.
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'sgc_escrow.escrow_release') or '/'
        records = super().create(vals_list)
        # Safety net: nothing should still read 'New' here, but a name slipped
        # through by an unknown path must never reach the unique index.
        records._assign_release_references()
        records._refresh_snapshots(default_amount=True)
        return records

    def _assign_release_references(self):
        """Assign the human reference from the Escrow Release sequence."""
        for record in self.filtered(lambda r: not r.name or r.name == _('New')):
            record._write_controlled({
                'name': self.env['ir.sequence'].next_by_code(
                    'sgc_escrow.escrow_release') or '/',
            })
    # -- Snapshots ---
    def _refresh_snapshots(self, default_amount=False):
        """Freeze the project figures this release is authorised against.

        Only ever called on draft records. Once approved, the numbers on the
        document are the numbers the approver signed.
        """
        for record in self:
            if record.state != 'draft':
                continue
            project = record.project_id
            if not project or not project.escrow_enabled:
                raise ValidationError(_(
                    'Cannot draft a release for %s: escrow is not enabled on that '
                    'project. Configure its escrow bank journal first.'
                ) % (project.display_name if project else _('(unknown project)')))

            received, released, _balance = project._escrow_ledger_totals()
            progress = project.escrow_certified_progress
            retention = project.escrow_retention_pct
            entitled = received * (progress / 100.0) * (1.0 - (retention / 100.0))
            releasable = max(0.0, entitled - released)

            record._write_controlled({
                'certified_progress_snapshot': progress,
                'retention_pct_snapshot': retention,
                'certified_by_snapshot': project.escrow_certified_by.id,
                'certified_date_snapshot': project.escrow_certified_date,
                'received_snapshot': received,
                'released_before_snapshot': released,
                'entitled_snapshot': entitled,
                'releasable_snapshot': releasable,
                'operating_journal_id': (
                    project.escrow_release_journal_id.id
                    or record._default_operating_journal_id()),
                'currency_id': project.escrow_currency_id.id or record.currency_id.id,
            })
            if default_amount and not record.amount:
                record._write_controlled({
                    'amount': record._currency_round(releasable),
                })

    def _default_operating_journal_id(self):
        """Fall back to the company's default bank journal."""
        return self._default_operating_journal_for(
            self.company_id or self.env.company)

    @api.model
    def _default_operating_journal_for(self, company):
        """First bank journal of ``company``; used pre-create and as fallback."""
        journal = self.env['account.journal'].search([
            ('type', '=', 'bank'),
            ('company_id', '=', company.id),
        ], limit=1)
        return journal.id if journal else False

    def _currency_round(self, amount):
        return self.currency_id.round(amount)

    def action_refresh_snapshots(self):
        """Re-baseline the snapshots against the project's current figures."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_(
                'Snapshots are frozen once a release leaves draft. Reverse the '
                'posted entry instead of editing an approved release.'
            ))
        self._refresh_snapshots(default_amount=True)
        return True

    @api.depends('amount', 'releasable_snapshot', 'is_override')
    def _compute_amount_exceeds_entitlement(self):
        for record in self:
            over = record.amount > record.releasable_snapshot
            record.amount_exceeds_entitlement = over and not record.is_override
            record.remaining_after_release = max(
                0.0, record.releasable_snapshot - record.amount)

    # -- Guards ---
    # Fields that may only be changed by the module's own action methods.
    # Write access on this model is necessary to approve and post (both
    # transition the record through write()), so without this guard a caller
    # holding write permission could jump a release straight to `posted`, or
    # rewrite the frozen entitlement snapshots it is supposed to be measured
    # against. A financial control that can be bypassed with one RPC call is
    # not a control.
    _CONTROLLED_FIELDS = (
        'state',
        'certified_progress_snapshot',
        'retention_pct_snapshot',
        'certified_by_snapshot',
        'certified_date_snapshot',
        'received_snapshot',
        'released_before_snapshot',
        'entitled_snapshot',
        'releasable_snapshot',
        'journal_entry_id',
        'reversal_entry_id',
        'escrow_line_id',
        'operating_line_id',
        'override_user_id',
        'name',
    )

    def write(self, vals):
        # The guard is lifted by a context flag rather than an instance
        # attribute, because context propagates through the whole nested write
        # chain (constraints, computes, mail tracking) whereas an attribute set
        # on one recordset would not be visible on a derived one.
        if self.env.context.get(_CONTROLLED_WRITE_KEY):
            return super().write(vals)

        attempted = [key for key in vals if key in self._CONTROLLED_FIELDS]
        if attempted:
            raise AccessError(_(
                'Escrow release fields %(fields)s are controlled by the release '
                'workflow and cannot be written directly. Use the Approve, Post, '
                'Reverse, Refresh Snapshots or Cancel actions instead.'
            ) % {'fields': ', '.join(sorted(attempted))})
        return super().write(vals)

    def _write_controlled(self, vals):
        """Write guarded fields from inside the workflow, bypassing the guard."""
        return self.with_context(**{_CONTROLLED_WRITE_KEY: True}).write(vals)

    @api.constrains('amount')
    def _check_amount_not_negative(self):
        """Drafts may be zero (nothing releasable yet) but never negative.

        Positivity is enforced at approval/post time by _check_entitlement(),
        not here: a release is a working document until it is committed.
        """
        for record in self:
            if record.amount < 0.0:
                raise ValidationError(_(
                    'Release amount cannot be negative (%s).'
                ) % record.name)

    def _check_entitlement(self):
        """Raise unless the amount is inside the certified entitlement."""
        for record in self:
            if record.amount <= 0.0:
                raise ValidationError(_(
                    'Release amount must be greater than zero (%s).'
                ) % record.name)
            if record.amount <= record.releasable_snapshot:
                continue
            if not record.is_override:
                raise UserError(_(
                    'Release %(name)s of %(amount)s exceeds the entitlement of '
                    '%(releasable)s for %(project)s.\n\n'
                    'Entitlement = %(received)s received x %(progress)s%% certified '
                    'progress x (1 - %(retention)s%% retention).\n\n'
                    'Withdrawals above certified progress need the bank\'s and '
                    'RERA\'s approval. If you hold one, tick "Override Entitlement" '
                    'and record why.'
                ) % {
                    'name': record.name,
                    'amount': record.amount,
                    'releasable': record.releasable_snapshot,
                    'project': record.project_id.display_name,
                    'received': record.received_snapshot,
                    'progress': record.certified_progress_snapshot,
                    'retention': record.retention_pct_snapshot,
                })
            if not record.override_reason or not record.override_reason.strip():
                raise ValidationError(_(
                    'An override release requires a written reason (%s).'
                ) % record.name)

    def _check_override_authorised(self):
        """Only an Escrow Manager may authorise an over-entitlement release."""
        group = self.env.ref(
            'sgc_escrow.group_escrow_manager', raise_if_not_found=False)
        for record in self:
            if not record.is_override:
                continue
            if group and not self.env.user.has_group('sgc_escrow.group_escrow_manager'):
                raise UserError(_(
                    'Only an Escrow Manager can release above the certified '
                    'entitlement. %s was attempted by %s.'
                ) % (record.name, self.env.user.display_name))

    @api.constrains('is_override')
    def _check_override_reason_present(self):
        """Once the release leaves draft, an override must carry its reason.

        On drafts the flag may be staged before the reason is typed
        (test_override_with_reason_is_accepted); approval still refuses an
        override without a reason through _check_entitlement().
        """
        for record in self:
            if record.state == 'draft':
                continue
            if record.is_override and not (record.override_reason or '').strip():
                raise ValidationError(_(
                    'An override release requires a written reason (%s).'
                ) % record.name)

    # -- Transitions ---
    def action_approve(self):
        """Freeze the figures and authorise the posting."""
        for record in self:
            if record.state != 'draft':
                raise UserError(_(
                    'Only draft releases can be approved (%s is %s).'
                ) % (record.name, record.state))
            record._check_override_authorised()
            record._check_entitlement()
            record._write_controlled({
                'state': 'approved',
                'is_override': record.is_override,
                'override_user_id': record.override_user_id.id
                or (self.env.user.id if record.is_override else False),
            })
            record.message_post(body=_('Release approved against %s%% certified '
                                       'progress.') % record.certified_progress_snapshot)
        return True

    def action_post(self):
        """Write the ledger entry: Dr operating bank / Cr escrow bank.

        Refused outright while ``sgc_escrow.posting_enabled`` is off (the
        default). See ``res_config_settings`` for why this gate exists.
        """
        self._check_posting_enabled()
        for record in self:
            if record.state != 'approved':
                raise UserError(_(
                    'Only approved releases can be posted (%s is %s).'
                ) % (record.name, record.state))
            record._check_override_authorised()
            record._check_entitlement()
            record._create_release_entry()
        return True

    @api.model
    def _check_posting_enabled(self):
        """Refuse to create accounting entries until explicitly enabled.

        Accounting-entry creation is deliberately deferred. The allocation
        register and the release approvals are built and signed off first; the
        historic invoice and receipt entries are then created, reconciled against
        this register, and only then is this switched on.
        """
        enabled = self.env['ir.config_parameter'].sudo().get_param(
            'sgc_escrow.posting_enabled', 'False')
        if str(enabled).lower() in ('true', '1'):
            return True
        raise UserError(_(
            'Posting escrow releases is disabled, so no accounting entry will be '
            'created.\n\n'
            'This is deliberate: the per-unit escrow allocation register is being '
            'built and reconciled first. Once the historic invoice and receipt '
            'entries exist and the register has been signed off against them, an '
            'administrator can enable it under Settings -> Property Management -> '
            'Escrow -> "Allow Escrow Releases to Post".'
        ))

    def _create_release_entry(self):
        """Post the two-line transfer. No P&L effect -- own funds only."""
        self.ensure_one()
        project = self.project_id
        escrow_journal = project.escrow_bank_journal_id
        escrow_account = project.escrow_account_id
        operating_account = self.operating_journal_id.default_account_id

        if not escrow_journal or not escrow_account:
            raise UserError(_(
                'Project %s has no escrow bank account configured.'
            ) % project.display_name)
        if not operating_account:
            raise UserError(_(
                'Operating journal %s has no default account to receive the '
                'released funds.'
            ) % self.operating_journal_id.display_name)
        if escrow_account == operating_account:
            raise UserError(_(
                'The operating journal is the same account as the escrow account '
                'for %s. Choose a different operating bank.'
            ) % project.display_name)

        Move = self.env['account.move']
        move = Move.create({
            'journal_id': escrow_journal.id,
            'date': self.date,
            'ref': _('Escrow Release %s') % self.name,
            'company_id': self.company_id.id,
            'currency_id': self.currency_id.id,
            'escrow_release_id': self.id,
            'line_ids': [
                # Credit the escrow account: money leaves the regulated account.
                (0, 0, {
                    'account_id': escrow_account.id,
                    'name': _('Release to operating bank - %s') % self.name,
                    'debit': 0.0,
                    'credit': self.amount,
                    'partner_id': project.escrow_agent_id.id or False,
                }),
                # Debit the operating bank: money arrives where it is spent from.
                (0, 0, {
                    'account_id': operating_account.id,
                    'name': _('Escrow release received - %s') % self.name,
                    'debit': self.amount,
                    'credit': 0.0,
                    'partner_id': project.escrow_agent_id.id or False,
                }),
            ],
        })
        move.action_post()

        escrow_line = move.line_ids.filtered(
            lambda l: l.account_id == escrow_account)
        operating_line = move.line_ids.filtered(
            lambda l: l.account_id == operating_account)

        self._write_controlled({
            'state': 'posted',
            'journal_entry_id': move.id,
            'escrow_line_id': escrow_line[:1].id,
            'operating_line_id': operating_line[:1].id,
        })
        self.message_post(body=_(
            'Posted %(amount)s from escrow to %(journal)s. Reference: %(ref)s.'
        ) % {
            'amount': self.amount,
            'journal': self.operating_journal_id.display_name,
            'ref': self.payment_reference or _('(none)'),
        })
        return move

    def action_reverse(self):
        """Reverse a posted release. History is append-only, never deleted."""
        for record in self:
            if record.state != 'posted':
                raise UserError(_(
                    'Only posted releases can be reversed (%s is %s).'
                ) % (record.name, record.state))
            if record.reversal_entry_id:
                raise UserError(_(
                    'Release %s was already reversed by %s.'
                ) % (record.name, record.reversal_entry_id.display_name))
            wizard = self.env['account.move.reversal'].create({
                'move_ids': [(4, record.journal_entry_id.id)],
                'date': fields.Date.context_today(self),
                'journal_id': record.journal_entry_id.journal_id.id,
            })
            # reverse_moves() returns an act_window dict; the created
            # reversals live on the wizard's new_move_ids.
            wizard.reverse_moves()
            reversal = wizard.new_move_ids
            record._write_controlled({
                'state': 'cancelled',
                'reversal_entry_id': reversal[:1].id if reversal else False,
            })
            record.message_post(body=_('Release reversed. Money returned to escrow.'))
        return True

    def action_cancel(self):
        """Cancel a release that has not touched the ledger."""
        for record in self:
            if record.state == 'posted':
                raise UserError(_(
                    'Release %s is posted. Use "Reverse" so the ledger history '
                    'stays intact.'
                ) % record.name)
            record._write_controlled({'state': 'cancelled'})
        return True

    def action_draft(self):
        for record in self:
            if record.state == 'posted':
                raise UserError(_(
                    'A posted release cannot be reset to draft. Reverse it instead.'
                ) % record.name)
            record._write_controlled({'state': 'draft'})
            record._refresh_snapshots(default_amount=True)
        return True

    # -- UI ---
    def action_view_journal_entry(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Escrow Release Journal Entry'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.journal_entry_id.id,
        }

    def action_view_project(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Project'),
            'res_model': 'property.project',
            'view_mode': 'form',
            'res_id': self.project_id.id,
        }

    def action_print_voucher(self):
        """Print the release voucher the escrow bank signs off against."""
        self.ensure_one()
        return self.env.ref(
            'sgc_escrow.action_report_escrow_release_voucher'
        ).report_action(self)
