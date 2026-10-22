# -*- coding: utf-8 -*-
"""The EOI / booking receipt.

One idea, one home: the money gate of this module asks the same question every
time - is there a POSTED customer receipt registered against this unit? - so the
answer, the posting and the unit link all live in this helper.

There is no parallel payment system here: a receipt is a real ``account.payment``
posted in Accounting, tied to the unit through ``manual_property_id`` (the
module that lets a standalone receipt carry a unit). Ticking a flag is not proof
of payment.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

VERIFIED_STATES_PARAM = 'sgc_eoi.payment_verified_states'
DEFAULT_VERIFIED_STATES = ('in_process', 'paid')


class SgcEoiReceiptHelper(models.AbstractModel):
    _name = 'sgc.eoi.receipt.helper'
    _description = 'EOI / booking receipt helper (posted receipt tied to a unit)'

    @api.model
    def _verified_states(self):
        """The payment states that count as money received."""
        raw = self.env['ir.config_parameter'].sudo().get_param(VERIFIED_STATES_PARAM) or ''
        states = tuple(s.strip() for s in raw.split(',') if s.strip())
        return states or DEFAULT_VERIFIED_STATES

    @api.model
    def _receipts_for_unit(self, unit):
        """The posted customer receipts registered against a unit."""
        return self.env['account.payment'].sudo().search([
            ('property_id', '=', unit.id),
            ('payment_type', '=', 'inbound'),
            ('state', 'in', list(self._verified_states())),
        ])

    @api.model
    def _received_for_unit(self, unit):
        """What the unit has actually received, in the company currency."""
        currency = (unit.company_id or unit.env.company).currency_id
        company = unit.company_id or unit.env.company
        total = 0.0
        for payment in self._receipts_for_unit(unit):
            total += payment.currency_id._convert(
                payment.amount, currency, company,
                payment.date or fields.Date.context_today(unit))
        return total

    @api.model
    def _create_receipt(self, unit, partner, journal, amount, date, memo):
        """Post a customer receipt in Accounting."""
        if amount <= 0:
            raise UserError(_('The receipt amount must be greater than zero.'))
        journal = journal.sudo()
        if journal.type not in ('bank', 'cash'):
            raise UserError(_('Choose a bank or cash journal to post the receipt in.'))
        company = unit.company_id or unit.env.company
        if journal.company_id != company:
            raise UserError(_('The receipt journal must belong to %s.', company.display_name))
        line = journal._get_available_payment_method_lines('inbound')[:1]
        if not line:
            raise UserError(_('Journal %s has no inbound payment method.', journal.display_name))
        payment = self.env['account.payment'].sudo().create({
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': partner.id,
            'amount': amount,
            'currency_id': (unit.currency_id or company.currency_id).id,
            'date': date or fields.Date.context_today(unit),
            'journal_id': journal.id,
            'payment_method_line_id': line.id,
            'memo': memo,
            'company_id': company.id,
        })
        payment.action_post()
        return payment

    @api.model
    def _register_against_unit(self, payment, unit):
        """Tie a receipt to the unit, so the money and the unit travel together."""
        payment = payment.sudo()
        if payment.property_id:
            if payment.property_id != unit:
                raise UserError(_(
                    'Receipt %s is already registered against unit %s.',
                    payment.display_name, payment.property_id.display_name))
            return payment
        if 'manual_property_id' not in payment._fields:
            raise UserError(_(
                'This database cannot register a receipt against a unit: the module '
                '"sgc_unit_link" is not installed. Install it and try again.'))
        payment.manual_property_id = unit.id
        if payment.property_id != unit:
            raise UserError(_(
                'Receipt %s could not be registered against unit %s. Check the unit '
                'link on the receipt.', payment.display_name, unit.display_name))
        return payment

    @api.model
    def _resolve_receipt(self, unit, partner, journal, amount, date, memo, existing=None):
        """The posted receipt for a stage: one that already exists, or a new one.

        Either way it comes back registered against the unit.
        """
        if existing:
            payment = existing.sudo()
            if payment.payment_type != 'inbound':
                raise UserError(_('%s is not a customer receipt.', payment.display_name))
            if payment.state not in self._verified_states():
                raise UserError(_(
                    'Receipt %s is not posted yet (status: %s). Post it in Accounting first.',
                    payment.display_name, payment.state))
            if partner and payment.partner_id != partner:
                raise UserError(_(
                    'Receipt %s belongs to %s, not to the purchaser.',
                    payment.display_name, payment.partner_id.display_name))
            if amount and payment.amount + 0.005 < amount:
                raise UserError(_(
                    'Receipt %s is %s, below the %s expected.',
                    payment.display_name, payment.amount, amount))
            return self._register_against_unit(payment, unit)
        payment = self._create_receipt(unit, partner, journal, amount, date, memo)
        return self._register_against_unit(payment, unit)
