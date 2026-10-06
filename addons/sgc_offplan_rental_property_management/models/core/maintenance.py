# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
import json
import logging

import requests

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class PropertyMaintenance(models.Model):
    # Odoo 19 (odoo/orm/models.py, MetaModel.__new__): a *list* `_inherit` with
    # no explicit `_name` no longer defaults the model name to `_inherit[0]`;
    # the class name is used instead.  The 19.0.2.62 scratch run caught exactly
    # that: "Class PropertyMaintenance has no _name, please make it explicit:
    # _name = 'property.maintenance'".  The explicit `_name` keeps this class an
    # extension of maintenance.request while the audit mixin rides along.
    _name = 'maintenance.request'
    _inherit = ['maintenance.request', 'sgc.critical.audit.mixin']

    # Entry 52 capture scope: identity, lifecycle, estate links, money, AMC/CMC
    # terms. AI triage output stays out (derived, non-authoritative).
    _audit_watched_fields = frozenset({
        'name', 'description', 'stage_id', 'priority', 'schedule_date',
        'close_date', 'maintenance_type', 'property_id', 'tenancy_id',
        'landlord_id', 'maintenance_type_id', 'payment_from', 'payment_type',
        'customer_id', 'vendor_id', 'rent_contract_id', 'sell_contract_id',
        'tenant_id', 'landlord_approval_state', 'landlord_approved_date',
        'landlord_rejection_reason', 'total', 'amc_contract_type',
        'scope_of_work', 'service_frequency', 'site_supervisor_id',
        'sla_response_hours', 'contract_start_date', 'contract_end_date',
        'annual_fee', 'exclusions',
    })

    property_id = fields.Many2one('property.details', string='Property', index=True)
    tenancy_id = fields.Many2one('tenancy.details')
    company_id = fields.Many2one('res.company', string='Company',
                                 default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id',
                                  string='Currency')
    landlord_id = fields.Many2one('res.partner', string='LandLord')
    maintenance_type_id = fields.Many2one('product.template', string='Type',
                                          domain=[('is_maintenance', '=', True)])
    price = fields.Float(related='maintenance_type_id.list_price',
                         string='Price')
    invoice_id = fields.Many2one('account.move', string='Invoice')
    invoice_state = fields.Boolean(string='State')

    bill_id = fields.Many2one('account.move', string="Bill")
    bill_state = fields.Boolean(string="State ")

    invoice_count = fields.Integer(string="Invoice Count", compute="_compute_invoice_count")
    bill_count = fields.Integer(string="Bill Count", compute="_compute_bill_count")

    payment_from = fields.Selection([('customer', 'Customer'), ('vendor', 'Vendor')], string="Payment From", default="customer")
    payment_type = fields.Selection([('invoice', 'Invoice'), ('bill', 'Bill')], string="Payment Type", default="invoice")
    customer_id = fields.Many2one('res.partner', string="Customer")
    vendor_id = fields.Many2one('res.partner', string="Vendor")
    maintenance_product_ids = fields.One2many('maintenance.product.line', 'maintenance_id')
    total_untaxed_amount = fields.Monetary(string="Total Untaxed Amount", compute="_compute_total_untaxed_amount")
    total = fields.Monetary(string="Total")

    rent_contract_id = fields.Many2one('tenancy.details', string="Rent Contract")
    sell_contract_id = fields.Many2one('property.vendor', string="Sell Contract")

    tenant_id = fields.Many2one('res.partner', string='Tenant')
    landlord_approval_state = fields.Selection([('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], string='Landlord Approval', default='pending')
    landlord_approved_date = fields.Datetime(string='Landlord Approval Date')
    landlord_rejection_reason = fields.Text(string='Landlord Rejection Reason')

    # ── UAE AMC/CMC contract fields ──────────────────────────────────────────
    # Added for the maintenance/AMC contract report; not yet exposed on the
    # form view (follow-up task, outside the scope of the report work).
    amc_contract_type = fields.Selection([
        ('amc', 'AMC — Labour Only'),
        ('cmc', 'CMC — All Inclusive (Labour + Parts)'),
    ], string='Contract Type', default='amc')
    scope_of_work = fields.Text(
        string='Scope of Work',
        help='e.g. HVAC, Electrical, Plumbing, Fire & Life Safety, Lifts & Generators')
    service_frequency = fields.Char(string='PPM Visit Frequency', help='e.g. Quarterly, Monthly')
    site_supervisor_id = fields.Many2one('res.users', string='Site Supervisor')
    sla_response_hours = fields.Float(string='SLA Response Time (Hours)')
    contract_start_date = fields.Date(string='Contract Start Date')
    contract_end_date = fields.Date(string='Contract End Date')
    annual_fee = fields.Monetary(string='Annual Contract Fee')
    exclusions = fields.Text(string='Exclusions')

    # ── AI maintenance triage (LLM-assisted) ─────────────────────────────────
    # Populated on demand by action_ai_triage() via the server-side LLM proxy.
    # Both fields stay blank when the LLM is unreachable or unconfigured: triage
    # is an enhancement and must never block a request from being created/saved.
    ai_priority = fields.Selection([
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ], string='AI Priority', readonly=True, copy=False)
    ai_summary = fields.Text(string='AI Summary', readonly=True, copy=False)

    # System Parameters (Settings ▸ Technical ▸ System Parameters) that point the
    # triage at the server-side LLM proxy. Kept out of code so the endpoint/key
    # can change without a module upgrade.
    _AI_TRIAGE_ENDPOINT_PARAM = 'sgc_ai.triage_endpoint'   # full chat/completions URL
    _AI_TRIAGE_KEY_PARAM = 'sgc_ai.triage_api_key'         # unified API key (secret)
    _AI_TRIAGE_MODEL_PARAM = 'sgc_ai.triage_model'         # model id, e.g. gpt-oss-120b
    _AI_TRIAGE_PRIORITIES = ('low', 'medium', 'high', 'urgent')

    def action_ai_triage(self):
        """Ask the server-side LLM proxy to summarise each request and assign an
        urgency level, writing the result to ``ai_priority``/``ai_summary``.

        Manual, on-demand trigger (safer first cut than a synchronous call on
        every create). Any failure — unconfigured, network, auth, malformed
        response — is swallowed: the fields are left untouched and the request
        is never blocked. Returns a non-blocking UI notification for feedback.
        """
        icp = self.env['ir.config_parameter'].sudo()
        endpoint = (icp.get_param(self._AI_TRIAGE_ENDPOINT_PARAM) or '').strip()
        api_key = (icp.get_param(self._AI_TRIAGE_KEY_PARAM) or '').strip()
        model = (icp.get_param(self._AI_TRIAGE_MODEL_PARAM) or 'gpt-oss-120b').strip()

        if not endpoint or not api_key:
            _logger.info(
                "AI triage skipped: set System Parameters '%s' and '%s'.",
                self._AI_TRIAGE_ENDPOINT_PARAM, self._AI_TRIAGE_KEY_PARAM)
            return self._ai_triage_notify(_(
                "AI triage is not configured yet. An administrator must set the "
                "LLM endpoint and API key in System Parameters."))

        triaged = 0
        for record in self:
            priority, summary = record._ai_triage_call(endpoint, api_key, model)
            if priority or summary:
                record.write({
                    'ai_priority': priority or record.ai_priority,
                    'ai_summary': summary or record.ai_summary,
                })
                triaged += 1

        if not triaged:
            return self._ai_triage_notify(_(
                "AI triage could not reach the LLM service. The request was saved "
                "unchanged; check the server logs for details."), warn=True)
        return self._ai_triage_notify(_("AI triage complete."))

    def _ai_triage_call(self, endpoint, api_key, model):
        """Return ``(priority, summary)`` from the LLM, or ``('', '')`` on any
        failure. Never raises — triage must not block the maintenance request."""
        self.ensure_one()
        prop = self.property_id.name or self.equipment_id.name or 'N/A'
        mtype = self.maintenance_type_id.name or 'N/A'
        raw_desc = self.description or self.name or ''
        desc = html2plaintext(raw_desc).strip() if raw_desc else 'N/A'
        prompt = (
            "You are a triage assistant for a property maintenance team. Given a "
            "tenant maintenance request, respond with ONLY a compact JSON object "
            "of the form {\"priority\": <one of low|medium|high|urgent>, "
            "\"summary\": <one sentence>}. No markdown, no extra text.\n\n"
            "Request type: %s\nProperty: %s\nDescription: %s" % (mtype, prop, desc)
        )
        payload = {
            'model': model,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': 0,
            'max_tokens': 200,
        }
        try:
            resp = requests.post(
                endpoint,
                headers={
                    'Authorization': 'Bearer %s' % api_key,
                    'Content-Type': 'application/json',
                },
                data=json.dumps(payload),
                timeout=20,
            )
            resp.raise_for_status()
            content = resp.json()['choices'][0]['message']['content']
        except Exception as exc:  # noqa: BLE001 - triage must degrade gracefully
            _logger.warning("AI triage LLM call failed for request %s: %s", self.id, exc)
            return '', ''
        return self._ai_triage_parse(content)

    def _ai_triage_parse(self, content):
        """Best-effort parse of the LLM reply into ``(priority, summary)``."""
        text = (content or '').strip()
        if text.startswith('```'):
            text = text.strip('`')
            if text[:4].lower() == 'json':
                text = text[4:]
        priority, summary = '', ''
        try:
            start, end = text.find('{'), text.rfind('}')
            if start != -1 and end > start:
                data = json.loads(text[start:end + 1])
                priority = str(data.get('priority', '')).strip().lower()
                summary = str(data.get('summary', '')).strip()
        except (ValueError, TypeError):
            pass
        if priority not in self._AI_TRIAGE_PRIORITIES:
            priority = ''
        if not summary:
            summary = text[:500]  # fallback: keep the raw reply as the summary
        return priority, summary

    def _ai_triage_notify(self, message, warn=False):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("AI Triage"),
                'message': message,
                'type': 'warning' if warn else 'success',
                'sticky': False,
            },
        }

    def action_landlord_approve(self):
        self.write({
            'landlord_approval_state': 'approved',
            'landlord_approved_date': fields.Datetime.now(),
        })

    def action_landlord_reject(self, reason=None):
        self.write({
            'landlord_approval_state': 'rejected',
            'landlord_approved_date': fields.Datetime.now(),
            'landlord_rejection_reason': reason,
        })

    @api.onchange('property_id')
    def _onchange_property_id_set_tenant(self):
        if not self.property_id:
            return
        tenant = self.env['rent.contract'].search([
            ('property_id', '=', self.property_id.id),
            ('state', '=', 'active'),
        ], limit=1).tenant_id
        if not tenant:
            tenant = self.env['tenancy.details'].search([
                ('property_id', '=', self.property_id.id),
                ('state', '=', 'active'),
            ], limit=1).tenant_id
        if tenant:
            self.tenant_id = tenant

    def action_crete_invoice(self):
        if not self.maintenance_product_ids:
            raise ValidationError(_("Add Product for create invoice"))
        invoice_lines = [
            (0, 0, {
                'product_id': product.product_id.id,
                'name': product.description,
                'quantity': product.quantity,
                'price_unit': product.price_unit,
                'tax_ids': product.tax_ids.ids,
            }) for product in self.maintenance_product_ids
        ]
        data = {
            'move_type': 'out_invoice',
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': invoice_lines,
            'maintenance_request_id': self.id
        }
        if self.payment_from == 'customer':
            if not self.customer_id:
                raise ValidationError(_("Add customer to create invoice"))
            data['partner_id'] = self.customer_id.id
        else:
            if not self.vendor_id:
                raise ValidationError(_("Add vendor to create invoice"))
            data['partner_id'] = self.vendor_id.id
        invoice_id = self.env['account.move'].sudo().create(data)
        invoice_post_type = self.env['ir.config_parameter'].sudo(
        ).get_param('sgc_offplan_rental_property_management.invoice_post_type')
        if invoice_post_type == 'automatically':
            invoice_id.action_post()
        self.invoice_id = invoice_id.id
        self.total = invoice_id.amount_total
        self.invoice_state = True

        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoice',
            'res_model': 'account.move',
            'res_id': invoice_id.id,
            'view_mode': 'form',
            'target': 'current'
        }

    def action_crete_bill(self):
        if not self.maintenance_product_ids:
            raise ValidationError(_("Add Product for create bill"))
        bill_lines = [
            (0, 0, {
                'product_id': product.product_id.id,
                'name': product.description,
                'quantity': product.quantity,
                'price_unit': product.price_unit,
                'tax_ids': product.tax_ids.ids,
            }) for product in self.maintenance_product_ids
        ]
        data = {
            'move_type': 'in_invoice',
            'invoice_date': fields.Date.today(),
            'invoice_line_ids': bill_lines,
            'maintenance_request_id': self.id
        }
        if self.payment_from == 'customer':
            if not self.customer_id:
                raise ValidationError(_("Add customer to create bill"))
            data['partner_id'] = self.customer_id.id
        else:
            if not self.vendor_id:
                raise ValidationError(_("Add vendor to create bill"))
            data['partner_id'] = self.vendor_id.id

        bill_id = self.env['account.move'].sudo().create(data)
        invoice_post_type = self.env['ir.config_parameter'].sudo(
        ).get_param('sgc_offplan_rental_property_management.invoice_post_type')
        if invoice_post_type == 'automatically':
            bill_id.action_post()
        self.bill_id = bill_id.id
        self.total = bill_id.amount_total
        self.bill_state = True

        return {
            'type': 'ir.actions.act_window',
            'name': 'Bill',
            'res_model': 'account.move',
            'res_id': bill_id.id,
            'view_mode': 'form',
            'target': 'current'
        }

    @api.depends('maintenance_product_ids')
    def _compute_total_untaxed_amount(self):
        for rec in self:
            total_amount = 0.0
            if rec.maintenance_product_ids:
                for product in rec.maintenance_product_ids:
                    total_amount += product.price_subtotal
            rec.total_untaxed_amount = total_amount

    def _compute_invoice_count(self):
        """Compute invoice count - Optimized to use search_count."""
        for rec in self:
            rec.invoice_count = self.env['account.move'].sudo().search_count([
                ('maintenance_request_id', '=', rec.id),
                ('move_type', '=', 'out_invoice')
            ])

    def _compute_bill_count(self):
        """Compute bill count - Optimized to use search_count."""
        for rec in self:
            rec.bill_count = self.env['account.move'].sudo().search_count([
                ('maintenance_request_id', '=', rec.id),
                ('move_type', '=', 'in_invoice')
            ])

    def action_view_invoice(self):
        return {
            "name": "Invoices",
            "type": "ir.actions.act_window",
            "domain": [("maintenance_request_id", "=", self.id)],
            "view_mode": "list,form",
            'context': {'create': False},
            "res_model": "account.move",
            "target": "current",
        }

    def action_view_bills(self):
        return {
            "name": "Bills",
            "type": "ir.actions.act_window",
            "domain": [("maintenance_request_id", "=", self.id)],
            "view_mode": "list,form",
            'context': {'create': False},
            "res_model": "account.move",
            "target": "current",
        }

class MaintenanceProduct(models.Model):
    _inherit = 'product.template'

    is_maintenance = fields.Boolean(string='Maintenance')


class MaintenanceProductLine(models.Model):
    """Maintenance Product Line"""
    _name = 'maintenance.product.line'
    _inherit = ['sgc.critical.audit.mixin']
    _description = __doc__
    _rec_name = "product_id"

    # Entry 52 scope: the priced lines. Line model -> delete-gate exempt.
    _audit_watched_fields = frozenset({
        'maintenance_id', 'product_id', 'quantity', 'description',
        'price_unit', 'tax_ids',
    })
    _audit_unlink_requires_reason = False

    maintenance_id = fields.Many2one('maintenance.request', string="Maintenance")
    product_id = fields.Many2one('product.product', string="Product")

    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', string='Currency')

    quantity = fields.Integer(string="Quantity", default=1)
    description = fields.Char(string="Description")
    price_unit = fields.Monetary(string="Price")
    tax_ids = fields.Many2many('account.tax', string="Taxes", domain=[('type_tax_use', '=', 'sale')])
    price_subtotal = fields.Monetary(string="Amount", compute="_compute_price_subtotal")

    @api.onchange('product_id')
    def _onchange_product_get_details(self):
        for rec in self:
            rec.price_unit = rec.product_id.lst_price
            if rec.product_id.taxes_id:
                rec.tax_ids = rec.product_id.taxes_id.ids
            rec.description = rec.product_id.name

    @api.depends('product_id', 'quantity', 'price_unit')
    def _compute_price_subtotal(self):
        for rec in self:
            total_amount = 0.0
            if rec.product_id:
                total_amount = rec.quantity * rec.price_unit
            rec.price_subtotal = total_amount
