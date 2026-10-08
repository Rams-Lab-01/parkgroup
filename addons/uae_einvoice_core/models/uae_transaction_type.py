# Part of Odoo. See LICENSE file for full copyright and licensing details.
"""8-bit ProfileExecutionID flag engine for PINT-AE per runbook section 8.2.

Bit order (LSB=bit 0, MSB=bit 7):
    bit 0  Free Trade Zone
    bit 1  Deemed Supply
    bit 2  Profit Margin Scheme
    bit 3  Summary Invoice
    bit 4  Continuous Supply
    bit 5  Disclosed Agent Billing
    bit 6  E-commerce Supply
    bit 7  Exports

The ``profile_execution_id`` integer is the single source of truth. The
8 named boolean fields are derived (computed + stored) from the integer,
so the round-trip is unambiguous: write the integer, the booleans are
always in sync.

Caller is responsible for keeping the integer in the 0..255 range; the
field is declared Integer with no auto-mask. The compute applies & 0xFF
defensively so a stray 9-bit value still produces a sane boolean set.
"""

from odoo import api, fields, models


class UAETransactionType(models.Model):
    _name = "uae.einvoice.transaction.type"
    _description = "PINT-AE Transaction Type Flag Engine (ProfileExecutionID)"

    name = fields.Char(required=True, help="Human label, e.g. 'FTZ + Continuous'")
    move_id = fields.Many2one(
        "account.move",
        string="Invoice",
        ondelete="cascade",
        index=True,
    )

    # --- single source of truth: 8-bit integer ---
    profile_execution_id = fields.Integer(
        string="ProfileExecutionID",
        required=True,
        default=0,
        help="8-bit packed encoding. LSb = Free Trade Zone. "
             "Caller keeps the value in 0..255.",
    )

    # --- the 8 named booleans (runbook section 8.2), all computed from integer ---
    flag_free_trade_zone = fields.Boolean(
        string="Free Trade Zone", compute="_compute_flags", store=True,
    )
    flag_deemed_supply = fields.Boolean(
        string="Deemed Supply", compute="_compute_flags", store=True,
    )
    flag_profit_margin = fields.Boolean(
        string="Profit Margin Scheme", compute="_compute_flags", store=True,
    )
    flag_summary_invoice = fields.Boolean(
        string="Summary Invoice", compute="_compute_flags", store=True,
    )
    flag_continuous_supply = fields.Boolean(
        string="Continuous Supply", compute="_compute_flags", store=True,
    )
    flag_disclosed_agent = fields.Boolean(
        string="Disclosed Agent Billing", compute="_compute_flags", store=True,
    )
    flag_ecommerce = fields.Boolean(
        string="E-commerce Supply", compute="_compute_flags", store=True,
    )
    flag_exports = fields.Boolean(
        string="Exports", compute="_compute_flags", store=True,
    )

    # bit layout constant — exported as a class attr so tests and other
    # modules can reference the canonical ordering without copy/paste.
    FLAG_BIT_ORDER = (
        "flag_free_trade_zone",
        "flag_deemed_supply",
        "flag_profit_margin",
        "flag_summary_invoice",
        "flag_continuous_supply",
        "flag_disclosed_agent",
        "flag_ecommerce",
        "flag_exports",
    )

    @api.depends("profile_execution_id")
    def _compute_flags(self):
        for rec in self:
            value = (rec.profile_execution_id or 0) & 0xFF
            for bit, field_name in enumerate(self.FLAG_BIT_ORDER):
                rec[field_name] = bool(value & (1 << bit))

    def has_flag(self, field_name):
        """Return True if ``field_name`` is a known flag set on this record."""
        self.ensure_one()
        if field_name not in self.FLAG_BIT_ORDER:
            return False
        return bool(getattr(self, field_name))
