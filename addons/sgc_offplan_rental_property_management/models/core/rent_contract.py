# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
import logging
import time

from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)


class RentContract(models.Model):
    _name = "rent.contract"
    _description = "Rent Contract"
    _order = "id desc"
    _inherit = ["mail.thread", "mail.activity.mixin", "sgc.critical.audit.mixin"]

    # Identity
    name = fields.Char(
        string="Contract Reference", required=True, tracking=True,
        default=lambda self: _("New"), copy=False)
    company_id = fields.Many2one(
        "res.company", string="Company",
        default=lambda self: self.env.company)

    # Parties
    property_id = fields.Many2one(
        "property.details", string="Property", required=True, tracking=True)
    tenant_id = fields.Many2one(
        "res.partner", string="Tenant", required=True, tracking=True)
    landlord_id = fields.Many2one(
        "res.partner", string="Landlord", tracking=True)

    # Dates
    start_date = fields.Date(string="Start Date", required=True)
    end_date = fields.Date(string="End Date", required=True)

    # Financial
    currency_id = fields.Many2one(
        "res.currency", string="Currency",
        default=lambda self: self.env.company.currency_id)
    rent_amount = fields.Monetary(
        string="Rent Amount", currency_field="currency_id")
    security_deposit = fields.Monetary(
        string="Security Deposit", currency_field="currency_id")
    security_deposit_paid = fields.Boolean(
        string="Security Deposit Paid", default=False)
    deposit_paid_amount = fields.Monetary(
        string="Deposit Paid", currency_field="currency_id")
    deposit_returned_amount = fields.Monetary(
        string="Deposit Returned", currency_field="currency_id")
    deposit_deducted_amount = fields.Monetary(
        string="Deposit Deducted", currency_field="currency_id")
    renewal_requested = fields.Boolean(
        string="Renewal Requested", default=False)
    payment_frequency = fields.Selection([
        ("monthly", "Monthly"),
        ("quarterly", "Quarterly"),
        ("yearly", "Yearly"),
    ], string="Payment Frequency", default="monthly")
    payment_cheque_count = fields.Integer(string="Number of Cheques")

    # UAE Ejari-style contract fields
    ejari_registration_number = fields.Char(string="Ejari Registration Number")
    furnished_status = fields.Selection([
        ("furnished", "Furnished"),
        ("unfurnished", "Unfurnished"),
    ], string="Furnishing Status", default="unfurnished")
    maintenance_responsibility = fields.Selection([
        ("landlord", "Landlord"),
        ("tenant", "Tenant"),
        ("shared", "Shared"),
    ], string="Maintenance Responsibility", default="shared")

    # Payment Schedule
    payment_schedule_id = fields.Many2one(
        "payment.schedule", string="Payment Schedule",
        domain=[("schedule_type", "=", "rental")])

    # Notes
    notes = fields.Text(string="Notes")

    # State
    state = fields.Selection([
        ("draft", "Draft"),
        ("active", "Active"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),
    ], string="Status", default="draft", tracking=True)

    # E-signature fields
    signed_via_portal = fields.Boolean(
        string="Signed via Portal",
        readonly=True,
        help="Indicates if the tenant signed electronically via the portal."
    )

    # Computed
    duration_months = fields.Integer(
        string="Duration (Months)",
        compute="_compute_duration_months", store=True)
    total_rent = fields.Monetary(
        string="Total Rent", currency_field="currency_id",
        compute="_compute_total_rent", store=True)

    # Rent Bills
    rent_bill_count = fields.Integer(
        string="Rent Bills", compute="_compute_rent_bill_count")
    rent_bill_ids = fields.One2many(
        'rent.bill', 'contract_id',
        string='Rent Bill Lines',
        help='Rent bills generated for this contract, mirroring the sale '
             'contract installment plan tab.',
    )

    # -------------------------------------------------------------------------
    # Commission Distribution (dynamic lines)
    # -------------------------------------------------------------------------
    annual_rent_amount = fields.Monetary(
        string="Annual Rent", currency_field="currency_id",
        compute="_compute_annual_rent_amount", store=True,
        help="Rent amount normalized to a 12-month basis. Used as the commission "
             "calculation base, since rental commission is conventionally quoted "
             "against annual rent regardless of the lease term or payment frequency.")
    commission_line_ids = fields.One2many(
        'rent.commission.line', 'contract_id',
        string='Commission Lines',
        help='Dynamic commission distribution to external and internal parties',
    )
    commission_total_amount = fields.Monetary(
        string='Total Commission', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
    )
    commission_external_total = fields.Monetary(
        string='External Commission Total', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
    )
    commission_internal_total = fields.Monetary(
        string='Internal Commission Total', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
    )
    commission_line_count = fields.Integer(
        string='Commission Line Count',
        compute='_compute_commission_totals', store=True,
    )
    commission_bill_ids = fields.Many2many(
        'account.move',
        relation='rent_contract_commission_bill_rel',
        compute='_compute_commission_bill_ids',
        string='Commission Bills',
    )
    commission_bill_count = fields.Integer(
        string='Commission Bill Count',
        compute='_compute_commission_bill_ids',
    )
    commission_total_tax = fields.Monetary(
        string='Total Tax', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
        help='Sum of tax across all commission lines.')
    commission_amount_total = fields.Monetary(
        string='Total w/ Tax', currency_field='currency_id',
        compute='_compute_commission_totals', store=True,
        help='Grand total of commission lines including tax.')
    is_commission_eligible = fields.Boolean(
        string='Commission Eligible', compute='_compute_commission_eligibility')
    commission_ineligible_reason = fields.Char(
        string='Commission Ineligibility Reason', compute='_compute_commission_eligibility')

    @api.depends("start_date", "end_date")
    def _compute_duration_months(self):
        for rec in self:
            if rec.start_date and rec.end_date:
                delta = relativedelta(rec.end_date, rec.start_date)
                rec.duration_months = delta.years * 12 + delta.months
            else:
                rec.duration_months = 0

    @api.depends("rent_amount", "duration_months")
    def _compute_total_rent(self):
        for rec in self:
            rec.total_rent = rec.rent_amount * rec.duration_months

    @api.depends("rent_amount", "payment_frequency")
    def _compute_annual_rent_amount(self):
        periods = {"monthly": 12, "quarterly": 4, "yearly": 1}
        for rec in self:
            rec.annual_rent_amount = rec.rent_amount * periods.get(rec.payment_frequency, 12)

    def _compute_rent_bill_count(self):
        for rec in self:
            rec.rent_bill_count = self.env["rent.bill"].search_count(
                [("contract_id", "=", rec.id)])

    @api.depends('commission_line_ids.commission_amount', 'commission_line_ids.category')
    def _compute_commission_totals(self):
        for rec in self:
            lines = rec.commission_line_ids
            rec.commission_external_total = sum(
                l.commission_amount for l in lines if l.category == 'external')
            rec.commission_internal_total = sum(
                l.commission_amount for l in lines if l.category == 'internal')
            # Sum every line regardless of category (not just external + internal)
            # so an 'others' line isn't silently dropped from the grand total.
            rec.commission_total_amount = sum(lines.mapped('commission_amount'))
            rec.commission_line_count = len(lines)

    @api.depends('commission_line_ids.bill_id')
    def _compute_commission_bill_ids(self):
        for rec in self:
            bills = rec.commission_line_ids.bill_id
            rec.commission_bill_ids = bills
            rec.commission_bill_count = len(bills)

    @api.depends('state')
    def _compute_commission_eligibility(self):
        for rec in self:
            if rec.state == 'active':
                rec.is_commission_eligible = True
                rec.commission_ineligible_reason = False
            else:
                rec.is_commission_eligible = False
                rec.commission_ineligible_reason = _(
                    'Commission is eligible once the rent contract is confirmed (Active).')

    def _assign_reference(self):
        for contract in self:
            if not contract.name or contract.name == _('New'):
                contract.name = self.env['ir.sequence'].next_by_code('rent.contract') or _('New')

    @staticmethod
    def _check_end_date_present(vals):
        # end_date is required=True at the field level, but the ORM's own
        # required-field check does not intercept every create()/write() path
        # before the value reaches PostgreSQL's NOT NULL column constraint
        # (PROP-D2/PROP-D1 test_11 reproduced a raw NotNullViolation instead
        # of a friendly error). Guard explicitly, before super(), so every
        # entry vector (UI, RPC, import, batch) gets the same ValidationError.
        if 'end_date' in vals and not vals['end_date']:
            raise ValidationError(_(
                "An end date is required. This module does not support "
                "open-ended rent contracts."))

    def _find_overlap_conflict(self, property_id, start_date, end_date, exclude_id=None):
        if not property_id or not start_date or not end_date:
            return False
        domain = [
            ('property_id', '=', property_id),
            ('state', '=', 'active'),
            ('start_date', '<=', end_date),
            ('end_date', '>=', start_date),
        ]
        if exclude_id:
            domain.append(('id', '!=', exclude_id))
        return bool(self.search_count(domain))

    def _check_no_overlap_before_write(self, vals):
        # Rule B, checked BEFORE super().write() flushes to PostgreSQL:
        # the real EXCLUDE USING gist constraint (see init() below) fires
        # during flush, ahead of any @api.constrains method, which would
        # otherwise surface as a raw ExclusionViolation instead of a
        # friendly ValidationError on the ordinary create/write/activate path.
        if not ({'property_id', 'start_date', 'end_date', 'state'} & vals.keys()):
            return
        for contract in self:
            new_state = vals.get('state', contract.state)
            if new_state != 'active':
                continue
            new_property = vals['property_id'] if 'property_id' in vals else contract.property_id.id
            new_start = vals.get('start_date', contract.start_date)
            new_end = vals.get('end_date', contract.end_date)
            if self._find_overlap_conflict(new_property, new_start, new_end, exclude_id=contract.id):
                raise ValidationError(_(
                    "This property already has another active contract whose "
                    "occupancy dates overlap with %(name)s (%(start)s to %(end)s)."
                ) % {"name": contract.name, "start": new_start, "end": new_end})

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('rent.contract') or _('New')
            if not vals.get('end_date'):
                raise ValidationError(_(
                    "An end date is required. This module does not support "
                    "open-ended rent contracts."))
            if vals.get('state') == 'active' and self._find_overlap_conflict(
                    vals.get('property_id'), vals.get('start_date'), vals.get('end_date')):
                raise ValidationError(_(
                    "This property already has another active contract whose "
                    "occupancy dates overlap with the dates given."))
        return super(RentContract, self).create(vals_list)

    def write(self, vals):
        self._check_end_date_present(vals)
        self._check_no_overlap_before_write(vals)
        return super(RentContract, self).write(vals)

    @api.constrains('company_id', 'property_id', 'state')
    def _check_company_consistency(self):
        # PROP-D4: a contract's company must equal its property's company,
        # with no special-casing of a False company_id on either side.
        # 'state' is included as a trigger so activating a contract that was
        # made inconsistent by a means other than the normal create/write
        # chokepoints (e.g. direct SQL) is still caught.
        for contract in self:
            if not contract.property_id:
                continue
            if contract.company_id != contract.property_id.company_id:
                raise ValidationError(_(
                    "This contract's company (%(contract_company)s) does not "
                    "match its property's company (%(property_company)s)."
                ) % {
                    "contract_company": contract.company_id.name or _("None"),
                    "property_company": contract.property_id.company_id.name or _("None"),
                })

    def init(self):
        # Real, DB-level backstop for Rule B (PROP-D1 test_09): application
        # code alone is bypassable via raw SQL, so the exclusion constraint
        # must exist as an actual PostgreSQL constraint. Idempotent across
        # repeated module upgrades. daterange(..., '[]') treats end_date as
        # the last occupied day, so adjacent/touching ranges do not overlap.
        self.env.cr.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        self.env.cr.execute(
            "SELECT 1 FROM pg_constraint WHERE conname = 'rent_contract_no_overlap'"
        )
        if not self.env.cr.fetchone():
            self.env.cr.execute("""
                ALTER TABLE rent_contract
                ADD CONSTRAINT rent_contract_no_overlap
                EXCLUDE USING gist (
                    property_id WITH =,
                    daterange(start_date, end_date, '[]') WITH &&
                )
                WHERE (state = 'active')
            """)

    def _release_property_if_unoccupied(self):
        self.ensure_one()
        if not self.property_id:
            return
        today = fields.Date.context_today(self)
        still_occupied = self.search_count([
            ('id', '!=', self.id),
            ('property_id', '=', self.property_id.id),
            ('state', '=', 'active'),
            ('start_date', '<=', today),
            ('end_date', '>=', today),
        ])
        if not still_occupied:
            self.property_id.write({"state": "available"})

    # State transitions
    def action_activate(self):
        self.ensure_one()
        self._assign_reference()
        self.write({"state": "active"})
        if self.property_id:
            self.property_id.write({"state": "rented"})
        self.message_post(body=_("Contract activated. Property has been marked as rented."))

    def action_expire(self):
        self.ensure_one()
        self.write({"state": "expired"})
        self._release_property_if_unoccupied()
        self.message_post(body=_("Contract expired. Property is now available."))

    def action_cancel(self):
        self.ensure_one()
        self.write({"state": "cancelled"})
        self._release_property_if_unoccupied()
        self.message_post(body=_("Contract cancelled. Property is now available."))

    def action_request_renewal(self):
        self.ensure_one()
        self.renewal_requested = True
        self.message_post(body=_("Tenant requested lease renewal."))

    # CRON-38: bound the batch, commit per record, and retry with backoff.
    _EXPIRE_BATCH = 50
    _EXPIRE_RETRIES = 3

    @api.model
    def cron_expire_contracts(self):
        """Expire overdue active contracts - bounded and contention-tolerant.

        rent.contract is audited, and a cron has no concurrency retry wrapper
        (blocker 4: Odoo retries SerializationFailure/DeadlockDetected/
        LockNotAvailable for HTTP/RPC only). Under contention a whole-batch
        expiry would fail outright, so the batch is bounded, each record is
        committed on its own, and a failure is retried a bounded number of
        times with backoff. This method never raises.
        """
        today = fields.Date.context_today(self)
        ids = self.search([
            ("state", "=", "active"),
            ("end_date", "<", today),
        ], limit=self._EXPIRE_BATCH).ids
        done = failed = 0
        for cid in ids:
            for attempt in range(self._EXPIRE_RETRIES):
                try:
                    self.browse(cid).action_expire()
                    self.env.cr.commit()
                    done += 1
                    break
                except Exception as exc:  # noqa: BLE001 - a cron must not raise
                    self.env.cr.rollback()
                    if attempt + 1 >= self._EXPIRE_RETRIES:
                        failed += 1
                        _logger.error(
                            'Rent contract expiry failed for %s after %s attempts: %s',
                            cid, self._EXPIRE_RETRIES, exc)
                    else:
                        time.sleep(2 ** attempt)
        _logger.info('Rent contract expiry: expired=%s failed=%s batch_limit=%s',
                     done, failed, self._EXPIRE_BATCH)
        return True

    def action_generate_rent_bills(self):
        self.ensure_one()
        if not self.start_date or not self.end_date:
            raise UserError(
                _("Please set both a start date and an end date before generating rent bills."))
        if not self.rent_amount:
            raise UserError(
                _("Please set a rent amount before generating rent bills."))

        self.env["rent.bill"].search([("contract_id", "=", self.id)]).unlink()

        months_step = {"monthly": 1, "quarterly": 3, "yearly": 12}.get(
            self.payment_frequency, 1)
        period_amount = self.rent_amount * months_step

        invoice_post_type = self.env['ir.config_parameter'].sudo().get_param(
            'sgc_offplan_rental_property_management.invoice_post_type')

        # Rent-billing product (Rent Installment). Mirrors how the other
        # invoice-creating paths resolve their configured product so the generated
        # move line carries a product, its income account and taxes instead of a
        # bare name/quantity/price_unit line.
        rent_product_id = self.env['ir.config_parameter'].sudo().get_param(
            'sgc_offplan_rental_property_management.account_installment_item_id')
        rent_product = (
            self.env['product.product'].browse(int(rent_product_id))
            if rent_product_id else
            self.env.ref(
                'sgc_offplan_rental_property_management.property_product_1',
                raise_if_not_found=False)
        )
        if rent_product and not rent_product.exists():
            rent_product = self.env['product.product']
        income_account = (
            rent_product.product_tmpl_id._get_product_accounts().get('income')
            if rent_product else False
        )

        property_label = self.property_id.display_name or _("Property")
        tenancy = self.env["tenancy.details"].search(
            [("tenancy_id", "=", self.id)], limit=1)
        count = 0
        current_date = self.start_date
        while current_date <= self.end_date:
            description = _("Rent - %s") % current_date.strftime("%B %Y")
            line_vals = {
                "name": "%s - %s" % (property_label, description),
                "quantity": 1,
                "price_unit": period_amount,
            }
            if rent_product:
                line_vals["product_id"] = rent_product.id
                line_vals["tax_ids"] = [(6, 0, rent_product.taxes_id.ids)]
                if income_account:
                    line_vals["account_id"] = income_account.id
            move = self.env["account.move"].create({
                "move_type": "out_invoice",
                "partner_id": self.tenant_id.id,
                "invoice_date": current_date,
                "invoice_origin": self.name,
                "currency_id": self.currency_id.id,
                "invoice_line_ids": [(0, 0, line_vals)],
            })
            if invoice_post_type == 'automatically':
                move.action_post()
            self.env["rent.bill"].create({
                "contract_id": self.id,
                "tenancy_id": tenancy.id,
                "rent_no": self.env['ir.sequence'].next_by_code('rent.bill') or _('New'),
                "vendor_id": self.landlord_id.id,
                "bill_type": _("Rent"),
                "description": description,
                "invoice_date": current_date,
                "amount": period_amount,
                "rent_amount": period_amount,
                "currency_id": self.currency_id.id,
                "company_id": self.company_id.id,
                "rent_bill_id": move.id,
            })
            count += 1
            current_date = current_date + relativedelta(months=months_step)

        if count:
            self.message_post(
                body=_("%d rent bill(s) generated.") % count)

    def action_view_rent_bills(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Rent Bills"),
            "res_model": "rent.bill",
            "view_mode": "list,form",
            "domain": [("contract_id", "=", self.id)],
            "context": {"default_contract_id": self.id},
        }

    # -------------------------------------------------------------------------
    # One-click: generate bills for every approved commission line on this
    # contract that hasn't been billed yet (vendor bill to landlord/company,
    # or customer invoice to the tenant depending on each line's payer_type).
    # -------------------------------------------------------------------------
    def action_generate_commission_bills(self):
        for contract in self:
            billable = contract.commission_line_ids.filtered(
                lambda l: l.state == 'approved' and not l.bill_id)
            if not billable:
                continue
            bills = billable._generate_bills(post=True)
            contract.message_post(
                body=_('%d commission bill(s) generated for %d line(s).') % (
                    len(bills), len(billable)))
        return True

    def action_view_commission_bills(self):
        self.ensure_one()
        return {
            'name': _('Commission Bills'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.commission_bill_ids.ids)],
            'context': {'create': False},
        }

    # E-signature method
    def action_send_for_signature(self):
        self.ensure_one()
        self.signed_via_portal = True
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": "Signature request sent (MVP demo)",
                "type": "success",
            }
        }
