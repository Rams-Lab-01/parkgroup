# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Escrow tagging on ``account.move`` and ``account.move.line``.

Two jobs:

1. **Project attribution.** Every invoice raised from a sale contract inherits
   the project of the unit that contract is for, stored on both the move and
   its lines. That makes "everything billed for PARK Beach Residence I" a
   domain filter rather than a report somebody has to write.

2. **Release identification.** The journal entry produced when an escrow
   release is posted is tagged back to its ``escrow.release`` document. That
   tag is what separates an *authorised* withdrawal from any other money
   movement out of the escrow account, which is exactly the distinction the
   entitlement ceiling depends on.

Nothing in the ``account`` application is modified -- only extended.
"""

from odoo import api, fields, models


class AccountMoveEscrow(models.Model):
    _inherit = 'account.move'

    escrow_project_id = fields.Many2one(
        'property.project',
        string='Escrow Project',
        related='sold_id.property_id.project_id',
        store=True,
        readonly=True,
        index=True,
        help='Project of the unit this invoice was raised for. Attribution only -- '
             'the escrow bank account is configured on the project, not here.',
    )
    escrow_release_id = fields.Many2one(
        'escrow.release',
        string='Escrow Release',
        copy=False,
        index=True,
        ondelete='set null',
        help='Set only on the journal entry that moves money out of an escrow '
             'account. It is the authorisation record for that movement.',
    )
    escrow_bank_journal_id = fields.Many2one(
        'account.journal',
        string='Escrow Bank Journal',
        related='escrow_project_id.escrow_bank_journal_id',
        readonly=True,
        help='The escrow bank journal of the attributed project, surfaced so the '
             'invoice form can show where Register Payment will route the money. '
             'Odoo 19 view validation rejects dotted field names, hence the '
             'explicit related field.',
    )
    is_escrow_release = fields.Boolean(
        string='Is Escrow Release',
        compute='_compute_is_escrow_release',
        store=True,
        help='Technical field: the account tabs of this entry on the Escrow menu.',
    )

    @api.depends('escrow_release_id')
    def _compute_is_escrow_release(self):
        for move in self:
            move.is_escrow_release = bool(move.escrow_release_id)

    def _escrow_project_enabled(self):
        """The escrow-enabled project this invoice belongs to, if any.

        Returns an empty recordset when the invoice is not a sale-contract
        invoice, or when its project has escrow switched off -- both mean "this
        module has no opinion about where the money goes".
        """
        self.ensure_one()
        project = self.escrow_project_id
        return project if project.escrow_enabled else self.env['property.project']


class AccountMoveLineEscrow(models.Model):
    _inherit = 'account.move.line'

    escrow_project_id = fields.Many2one(
        'property.project',
        string='Escrow Project',
        related='move_id.escrow_project_id',
        store=True,
        index=True,
        help='Denormalised from the parent move so escrow reporting can filter the '
             'ledger without joining through the invoice.',
    )
    escrow_release_id = fields.Many2one(
        'escrow.release',
        string='Escrow Release',
        related='move_id.escrow_release_id',
        store=True,
        index=True,
    )