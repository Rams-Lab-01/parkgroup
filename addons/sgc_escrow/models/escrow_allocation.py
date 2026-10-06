# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""escrow.allocation -- the per-unit escrow allocation register.

One row per (project, unit) recording *what the source says was paid into escrow*
versus *what the project's escrow rules require*. This is the auditable answer to
the question "for this unit, how much of the buyer's money is sitting in escrow,
and is that the right amount?".

The register is deliberately a set of immutable *facts* loaded from source
statements (bank confirmations, client spreadsheets, the escrow agent's
allocation report). It never invents a figure and never overwrites an unknown:
when the source carries no allocation for a unit the row records the sales facts
it *does* carry and leaves ``allocated_amount`` empty, which surfaces the unit in
the "awaiting source data" report rather than silently booking zero.

Design note -- why this is not a subledger
---
This model stores *allocation*, not *movement*. Money movement is always read
from ``account.move.line`` (see ``property.project`` roll-ups). If a historic
allocation was never posted to the ledger, the variance between
``required_amount`` and ``allocated_amount`` on this register is what finance
signs off on before any opening-balance entry is booked.
"""

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# Fields whose change is financially material and therefore worth attesting in
# the critical-audit chain (see sgc.critical.audit.mixin, Entry 28 convention).
_ESCROW_ALLOCATION_WATCHED = frozenset({
    'project_id',
    'unit_id',
    'contract_id',
    'escrow_pct',
    'allocated_amount',
    'collected_amount',
    'sale_price_snapshot',
    'source_reference',
})


class EscrowAllocation(models.Model):
    """Per-unit escrow allocation register (facts, not movements)."""

    _name = 'escrow.allocation'
    _description = 'Escrow Allocation (per unit)'
    # mail.thread is not optional decoration here: the five ``tracking=True``
    # fields below are silently dead parameters on a model that does not inherit
    # it (Odoo only whitelists `tracking` via mail.thread's
    # _valid_field_parameter), and "who changed this allocation, and when" is the
    # first question anyone asks about a financial register.
    _inherit = ['mail.thread', 'sgc.critical.audit.mixin']
    _order = 'project_id, unit_id'
    _rec_name = 'unit_id'

    # Allocation rows are operational sub-records: a correction is made by
    # re-importing or editing the row, never by deleting it with a reason gate.
    _audit_unlink_requires_reason = False
    _audit_watched_fields = _ESCROW_ALLOCATION_WATCHED

    # Odoo 19 removed ``_sql_constraints``: the old attribute is accepted and
    # then ignored, so the DB constraint would silently never be created and the
    # register could end up with two rows for the same unit. Table constraints
    # are declared with models.Constraint now (same convention as the account
    # module, e.g. account_account._check_length_prefix).
    _unique_project_unit = models.Constraint(
        "UNIQUE(project_id, unit_id)",
        "Only one escrow allocation row per unit per project.",
    )

    # -- Identity ---
    project_id = fields.Many2one(
        'property.project',
        string='Project',
        required=True,
        ondelete='cascade',
        index=True,
    )
    unit_id = fields.Many2one(
        'property.details',
        string='Unit',
        required=True,
        ondelete='cascade',
        index=True,
    )
    contract_id = fields.Many2one(
        'sale.contract',
        string='Sale Contract',
        ondelete='set null',
        index=True,
        copy=False,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Buyer',
        compute='_compute_partner_id',
        store=True,
        readonly=False,
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

    # -- Source facts ---
    # ``sale_price_snapshot`` / ``collected_amount`` are *snapshots* taken at
    # import time. The live values stay on sale.contract / account.move; the
    # snapshot is what the source document said, so the register remains
    # reproducible after the live records move on.
    sale_price_snapshot = fields.Monetary(
        string='Sale Price (source)',
        currency_field='currency_id',
        help='Sale price exactly as stated by the source document at import time.',
    )
    collected_amount = fields.Monetary(
        string='Collected to Date (source)',
        currency_field='currency_id',
        help='Total collected from the buyer per the source document, whether or '
             'not it reached the escrow account.',
    )
    escrow_pct = fields.Float(
        string='Escrow % Required',
        digits=(16, 8),
        default=0.0,
        help='Percentage of the sale price that UAE escrow rules require the buyer '
             'to deposit into the project escrow account (e.g. 20.00 = 20%%). High '
             'precision on purpose: source percentages carry many decimals and '
             'rounding them would invent phantom over/under variances.',
    )
    allocated_amount = fields.Monetary(
        string='Allocated to Escrow (source)',
        currency_field='currency_id',
        help='Amount the source identifies as sitting in the project escrow account '
             'for this unit. Left empty when the source carries no allocation figure.',
    )

    # -- Derived (never stored money) ---
    required_amount = fields.Monetary(
        string='Required by Rules',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
        help='sale price x escrow % -- what the escrow rules require to be held.',
    )
    variance_amount = fields.Monetary(
        string='Variance',
        currency_field='currency_id',
        compute='_compute_amounts',
        store=True,
        help='Allocated minus Required. Negative means under-allocated against the '
             'rules; positive means over-allocated. Empty until an allocation figure '
             'is supplied.',
    )
    has_source_data = fields.Boolean(
        string='Source Allocation On File',
        default=False,
        help='Set when the source supplied an allocation figure -- including an '
             'explicit 0.00, which means "the source says nothing sits in escrow '
             'for this unit" and belongs in the under-allocation bucket. False '
             'means no figure at all: such units are reported, never treated as '
             'zero. A stored flag, not a compute: Odoo reads a NULL numeric back '
             'as 0.0, so a compute could not tell "missing" from "zero supplied".',
    )

    # -- Provenance / reconciliation ---
    source_reference = fields.Char(
        string='Source Reference',
        help='Document the figures were read from (bank confirmation number, escrow '
             'agent allocation report, client workbook sheet, etc.).',
    )
    source_imported_on = fields.Datetime(
        string='Source Imported On',
        default=fields.Datetime.now,
        readonly=True,
    )
    reconciliation_note = fields.Text(
        string='Reconciliation Note',
        help='Open item for finance sign-off. Used twice: the importer stamps it '
             'for rows whose source figures conflict with the computed breakdown, '
             'and finance records here how a unit\'s allocation was reconciled '
             'against the accounting ledger (citing the source document and '
             'explaining any residual difference).',
    )
    flag_code = fields.Char(
        string='Flag Code',
        readonly=True,
        index=True,
        help='Machine-readable reconciliation flag, e.g. BREAKDOWN_EXCEEDS_COLLECTED '
             'or OVERPAYMENT. Empty means the unit reconciled cleanly.',
    )
    flag_note = fields.Char(
        string='Flag Detail',
        readonly=True,
    )

    active = fields.Boolean(string='Active', default=True)

    @api.constrains('escrow_pct')
    def _check_escrow_pct(self):
        for record in self:
            if record.escrow_pct < 0.0 or record.escrow_pct > 100.0:
                raise ValidationError(_(
                    'Escrow %% must be between 0 and 100 (row %s has %.2f).'
                ) % (record.display_name, record.escrow_pct))

    @api.constrains('allocated_amount', 'collected_amount')
    def _check_non_negative(self):
        for record in self:
            if record.allocated_amount < 0.0:
                raise ValidationError(_(
                    'Allocated to Escrow cannot be negative (%s).'
                ) % record.display_name)
            if record.collected_amount < 0.0:
                raise ValidationError(_(
                    'Collected to Date cannot be negative (%s).'
                ) % record.display_name)

    @api.constrains('project_id', 'unit_id')
    def _check_unit_project_consistency(self):
        for record in self:
            if record.unit_id.project_id and record.unit_id.project_id != record.project_id:
                raise ValidationError(_(
                    'Unit %(unit)s belongs to project %(unit_project)s, not %(project)s.'
                ) % {
                    'unit': record.unit_id.display_name,
                    'unit_project': record.unit_id.project_id.display_name,
                    'project': record.project_id.display_name,
                })

    # -- Computes ---
    @api.depends('contract_id.buyer_id', 'partner_id')
    def _compute_partner_id(self):
        for record in self:
            if not record.partner_id and record.contract_id:
                record.partner_id = record.contract_id.buyer_id

    @api.depends('sale_price_snapshot', 'escrow_pct', 'allocated_amount',
                 'has_source_data')
    def _compute_amounts(self):
        for record in self:
            base = record.sale_price_snapshot
            record.required_amount = base * (record.escrow_pct / 100.0)
            if record.has_source_data:
                # A supplied figure -- even 0.00 -- is a fact and carries a real
                # variance. Only "no figure on file" keeps variance empty.
                record.variance_amount = (
                    (record.allocated_amount or 0.0) - record.required_amount)
            else:
                record.variance_amount = 0.0

    # -- Source-figure presence (kept honest for imports and manual edits) ---
    @api.model
    def _figure_supplied(self, value):
        """True when a figure was given: 0.0 counts, None/False do not."""
        return value is not None and value is not False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'has_source_data' not in vals:
                vals['has_source_data'] = self._figure_supplied(
                    vals.get('allocated_amount'))
        return super().create(vals_list)

    def write(self, vals):
        if 'allocated_amount' in vals and 'has_source_data' not in vals:
            vals = dict(
                vals,
                has_source_data=self._figure_supplied(
                    vals.get('allocated_amount')),
            )
        return super().write(vals)

    # -- Navigation ---
    def action_view_contract(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Sale Contract'),
            'res_model': 'sale.contract',
            'view_mode': 'form',
            'res_id': self.contract_id.id,
        }

    def action_view_unit(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Unit'),
            'res_model': 'property.details',
            'view_mode': 'form',
            'res_id': self.unit_id.id,
        }