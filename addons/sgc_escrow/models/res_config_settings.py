# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Escrow settings.

Accounting-entry creation is **deferred by default**. ``posting_enabled`` ships
``False``, and ``escrow.release.action_post()`` refuses to run until an
administrator deliberately switches it on in Settings. That makes "we are not
posting to the ledger yet" an enforced state rather than a promise, so the
allocation register can be built up and signed off first without any risk of a
journal entry appearing.
"""

from odoo import fields, models


class ResConfigSettingsEscrow(models.TransientModel):
    _inherit = 'res.config.settings'

    sgc_escrow_posting_enabled = fields.Boolean(
        string='Allow Escrow Releases to Post',
        default=False,
        config_parameter='sgc_escrow.posting_enabled',
        readonly=False,
        help='OFF (default): escrow releases can be drafted, approved and printed, '
             'but posting one is refused, so no journal entry is ever created. Turn '
             'this on only once the historic invoice and receipt entries exist and '
             'the allocation register has been reconciled against them.',
    )
    sgc_escrow_payment_policy = fields.Selection(
        [
            ('warn', 'Warn (log + notify on the invoice)'),
            ('block', 'Block (refuse to post)'),
            ('off', 'Off (no escrow policing)'),
        ],
        string='Escrow Payment Policy',
        default='warn',
        config_parameter='sgc_escrow.payment_policy',
        readonly=False,
        help='What to do when a buyer receipt for an escrow-enabled project is '
             'booked to a bank other than that project\'s escrow account.\n\n'
             'Warn is the safe default: it records the exception without stopping '
             'the finance team. Block is for hard DLD/RERA enforcement. Off lets '
             'accounting run unconstrained.',
    )
    sgc_escrow_default_retention_pct = fields.Float(
        string='Default Retention %',
        digits=(5, 2),
        default=5.0,
        config_parameter='sgc_escrow.default_retention_pct',
        readonly=False,
        help='Pre-filled on new project escrow configuration. The UAE statutory '
             'retention is 5%%. It can still be changed per project.',
    )