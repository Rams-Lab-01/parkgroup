# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Off-plan registration fields and workflow on ``sale.contract`` (the SPA).

This module never changes the contract state machine. It only observes the
``state`` field and reacts: signing activates the registration, cancelling
cancels it. Everything is prefixed ``offplan_reg_`` to avoid colliding with the
escrow / EOI additions on the same model.
"""

import logging
import re
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError

_logger = logging.getLogger(__name__)

OFFICER_GROUP = 'sgc_offplan_rental_property_management.property_rental_officer'
MANAGER_GROUP = 'sgc_offplan_rental_property_management.property_rental_manager'

# Free-text city / emirate -> UAE state code.
EMIRATE_CODE_BY_ALIAS = {
    'dubai': 'DU',
    'abu dhabi': 'AZ',
    'sharjah': 'SH',
    'ajman': 'AJ',
    'ras al khaimah': 'RK',
    'ras alkhaimah': 'RK',
    'rak': 'RK',
    'umm al quwain': 'UQ',
    'umm alquwain': 'UQ',
    'uaq': 'UQ',
    'fujairah': 'FU',
}

ACTIVE_STATES = ('pending', 'submitted', 'issued')


class SaleContract(models.Model):
    _inherit = 'sale.contract'

    # ------------------------------------------------------------------
    # Flags & rule resolution
    # ------------------------------------------------------------------
    offplan_reg_is_offplan = fields.Boolean(
        string='Off-Plan', compute='_compute_offplan_reg_is_offplan',
        store=True, tracking=True, readonly=False,
        help='True for an off-plan (new build) sale. Defaults from the unit '
             'listing category; edit it when the unit is not classified.')
    offplan_reg_needs_review = fields.Boolean(
        string='Needs Review', compute='_compute_offplan_reg_needs_review',
        store=True, tracking=True, readonly=False,
        help='Set when the off-plan flag or the emirate could not be determined '
             'automatically.')
    offplan_reg_emirate_id = fields.Many2one(
        'res.country.state', string='Emirate',
        compute='_compute_offplan_reg_emirate_id', store=True,
        tracking=True, readonly=False,
        domain="[('country_id.code', '=', 'AE')]",
        help='Resolved from the unit state, then the project state, then the '
             'unit/project city text. Edit it when unresolved.')
    offplan_reg_rule_id = fields.Many2one(
        'offplan.registration.rule', string='Registration Rule',
        compute='_compute_offplan_reg_rule_id', store=True, readonly=False,
        tracking=True)
    offplan_reg_rule_label = fields.Char(
        string='Registration Type', compute='_compute_offplan_reg_rule_label',
        store=True)
    offplan_reg_project_id = fields.Many2one(
        'property.project', string='Project', related='property_id.project_id',
        store=True, index=True, readonly=True)
    offplan_reg_required = fields.Boolean(
        string='Registration Required', compute='_compute_offplan_reg_required',
        store=True, tracking=True)
    offplan_reg_deadline_configured = fields.Boolean(
        string='Deadline Configured',
        compute='_compute_offplan_reg_deadline', store=True,
        help='True when the rule is verified and has a deadline.')

    # ------------------------------------------------------------------
    # Status / workflow
    # ------------------------------------------------------------------
    offplan_reg_status = fields.Selection([
        ('not_required', 'Not Required'),
        ('pending', 'Pending'),
        ('submitted', 'Submitted'),
        ('issued', 'Issued'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
        ('converted', 'Converted to Title Deed'),
    ], string='Registration Status', default='pending', required=True,
        tracking=True, copy=False)
    offplan_reg_submitted_on = fields.Datetime(
        string='Submitted On', readonly=True, copy=False)

    # ------------------------------------------------------------------
    # Dates
    # ------------------------------------------------------------------
    offplan_reg_base_date = fields.Date(
        string='SPA Base Date', compute='_compute_offplan_reg_base_date',
        store=True, readonly=False,
        help='The date the registration deadline is counted from.')
    offplan_reg_base_source = fields.Selection([
        ('spa_signed', 'SPA Signed'),
        ('contract_date', 'Contract Date'),
    ], string='Base Source', compute='_compute_offplan_reg_base_date', store=True)
    offplan_reg_deadline = fields.Date(
        string='Registration Deadline', compute='_compute_offplan_reg_deadline',
        store=True, tracking=True,
        help='Base date + the rule deadline. Empty when the rule is unverified '
             'or has no deadline configured.')
    offplan_reg_days_left = fields.Integer(
        string='Days Left', compute='_compute_offplan_reg_deadline', store=True)
    offplan_reg_overdue = fields.Boolean(
        string='Overdue', compute='_compute_offplan_reg_deadline', store=True,
        tracking=True)

    # ------------------------------------------------------------------
    # Certificate
    # ------------------------------------------------------------------
    offplan_reg_application_ref = fields.Char(
        string='Application Ref.', tracking=True, copy=False)
    offplan_reg_certificate_no = fields.Char(
        string='Certificate No.', tracking=True, copy=False)
    offplan_reg_issue_date = fields.Date(
        string='Issue Date', tracking=True, copy=False)
    offplan_reg_certificate = fields.Binary(
        string='Certificate File', attachment=True, copy=False)
    offplan_reg_certificate_filename = fields.Char(string='Certificate Filename')
    offplan_reg_rejection_reason = fields.Text(string='Rejection Reason', copy=False)
    offplan_reg_cancel_reason = fields.Text(string='Cancellation Reason', copy=False)

    # ------------------------------------------------------------------
    # Fees
    # ------------------------------------------------------------------
    offplan_reg_fee_amount = fields.Monetary(
        string='Registration Fee', currency_field='currency_id',
        compute='_compute_offplan_reg_fee_amount', store=True, readonly=False,
        help='Sale price x the rule fee percentage. Editable for a negotiated fee.')
    offplan_reg_fee_percentage = fields.Float(
        string='Fee %', digits=(5, 2),
        compute='_compute_offplan_reg_fee_amount', store=True, readonly=False)
    offplan_reg_fee_paid_by = fields.Selection([
        ('buyer', 'Buyer'),
        ('developer', 'Developer'),
        ('split', 'Split'),
    ], string='Fee Paid By', default='buyer', tracking=True)
    offplan_reg_fee_paid_date = fields.Date(string='Fee Paid Date')

    # ------------------------------------------------------------------
    # Cross-links & sharing
    # ------------------------------------------------------------------
    offplan_reg_title_deed_no = fields.Char(
        string='Title Deed No.', related='property_id.title_deed_number',
        readonly=True)
    offplan_reg_portal_visible = fields.Boolean(
        string='Visible on Portal', default=False, copy=False)
    offplan_reg_shared = fields.Boolean(string='Shared with Customer', default=False,
                                        copy=False)
    offplan_reg_last_shared_on = fields.Datetime(
        string='Last Shared On', readonly=True, copy=False)
    offplan_reg_share_log_ids = fields.One2many(
        'offplan.registration.share.log', 'contract_id',
        string='Share Log')
    offplan_reg_share_count = fields.Integer(
        string='Shares', compute='_compute_offplan_reg_share_count')

    # ==================================================================
    # Computes
    # ==================================================================
    @api.depends('property_id.listing_category')
    def _compute_offplan_reg_is_offplan(self):
        for rec in self:
            category = rec.property_id.listing_category
            if category == 'offplan_sale':
                rec.offplan_reg_is_offplan = True
            elif category:
                rec.offplan_reg_is_offplan = False
            else:
                # Undetermined: keep whatever the user set, default False.
                rec.offplan_reg_is_offplan = rec.offplan_reg_is_offplan or False

    def _offplan_reg_resolve_emirate(self):
        """unit state -> project state -> city text (unit, then project)."""
        self.ensure_one()
        State = self.env['res.country.state']
        prop = self.property_id
        if prop.state_id:
            return prop.state_id
        if prop.project_id.state_id:
            return prop.project_id.state_id
        for text in (prop.city, prop.project_id.city):
            if not text:
                continue
            key = re.sub(r'[^a-z ]', '', text.lower()).strip()
            key = re.sub(r'\s+', ' ', key)
            code = EMIRATE_CODE_BY_ALIAS.get(key)
            if code:
                state = State.search(
                    [('code', '=', code), ('country_id.code', '=', 'AE')], limit=1)
                if state:
                    return state
        return State

    @api.depends('property_id.state_id', 'property_id.project_id.state_id',
                 'property_id.city', 'property_id.project_id.city')
    def _compute_offplan_reg_emirate_id(self):
        for rec in self:
            rec.offplan_reg_emirate_id = rec._offplan_reg_resolve_emirate()

    @api.depends('offplan_reg_emirate_id')
    def _compute_offplan_reg_rule_id(self):
        Rule = self.env['offplan.registration.rule']
        for rec in self:
            if rec.offplan_reg_emirate_id:
                rec.offplan_reg_rule_id = Rule.search(
                    [('emirate_id', '=', rec.offplan_reg_emirate_id.id),
                     ('active', '=', True)], limit=1)
            else:
                rec.offplan_reg_rule_id = False

    @api.depends('offplan_reg_rule_id', 'offplan_reg_rule_id.local_reg_name')
    def _compute_offplan_reg_rule_label(self):
        for rec in self:
            rule = rec.offplan_reg_rule_id
            if rule and rule.local_reg_name:
                emirate = rule.emirate_id.name or ''
                rec.offplan_reg_rule_label = '(%s \u2013 %s)' % (rule.local_reg_name, emirate)
            else:
                rec.offplan_reg_rule_label = False

    @api.depends('offplan_reg_is_offplan', 'offplan_reg_rule_id',
                 'offplan_reg_rule_id.mandatory')
    def _compute_offplan_reg_required(self):
        for rec in self:
            rule = rec.offplan_reg_rule_id
            rec.offplan_reg_required = bool(
                rec.offplan_reg_is_offplan and rule and rule.mandatory)

    @api.depends('offplan_reg_is_offplan', 'offplan_reg_emirate_id',
                 'offplan_reg_rule_id', 'property_id.listing_category')
    def _compute_offplan_reg_needs_review(self):
        for rec in self:
            unresolved = (not rec.property_id.listing_category) or (not rec.offplan_reg_emirate_id)
            if rec.offplan_reg_is_offplan and not rec.offplan_reg_rule_id:
                unresolved = True
            # `readonly=False` lets an operator clear the flag; do not flip an
            # already-resolved record back on unless a dependency is unresolved.
            rec.offplan_reg_needs_review = bool(unresolved)

    @api.depends('spa_signed_date', 'contract_date')
    def _compute_offplan_reg_base_date(self):
        for rec in self:
            if rec.spa_signed_date:
                rec.offplan_reg_base_date = rec.spa_signed_date
                rec.offplan_reg_base_source = 'spa_signed'
            elif rec.contract_date:
                rec.offplan_reg_base_date = rec.contract_date
                rec.offplan_reg_base_source = 'contract_date'
            else:
                rec.offplan_reg_base_date = False
                rec.offplan_reg_base_source = False

    @api.depends('offplan_reg_base_date', 'offplan_reg_rule_id',
                 'offplan_reg_rule_id.deadline_days', 'offplan_reg_rule_id.rule_verified')
    def _compute_offplan_reg_deadline(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rule = rec.offplan_reg_rule_id
            configured = bool(rule and rule.rule_verified and rule.deadline_days)
            rec.offplan_reg_deadline_configured = configured
            if configured and rec.offplan_reg_base_date:
                deadline = rec.offplan_reg_base_date + timedelta(days=rule.deadline_days)
                rec.offplan_reg_deadline = deadline
                rec.offplan_reg_days_left = (deadline - today).days
                rec.offplan_reg_overdue = deadline < today
            else:
                rec.offplan_reg_deadline = False
                rec.offplan_reg_days_left = 0
                rec.offplan_reg_overdue = False

    @api.depends('sale_price', 'offplan_reg_rule_id',
                 'offplan_reg_rule_id.fee_percentage')
    def _compute_offplan_reg_fee_amount(self):
        for rec in self:
            rule = rec.offplan_reg_rule_id
            pct = rule.fee_percentage if rule else 0.0
            rec.offplan_reg_fee_percentage = pct or 0.0
            rec.offplan_reg_fee_amount = (rec.sale_price or 0.0) * (pct or 0.0) / 100.0

    @api.depends('offplan_reg_share_log_ids')
    def _compute_offplan_reg_share_count(self):
        for rec in self:
            rec.offplan_reg_share_count = len(rec.offplan_reg_share_log_ids)

    # ==================================================================
    # ORM hooks (observe the state machine, never change it)
    # ==================================================================
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._offplan_reg_apply_reference()
            rec._offplan_reg_sync_required()
            rec._offplan_reg_ensure_manager_activity()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('offplan_reg_syncing'):
            return res
        touched = {'state', 'offplan_reg_is_offplan', 'offplan_reg_emirate_id',
                   'property_id'} & set(vals)
        if not touched:
            return res
        new_state = vals.get('state')
        for rec in self:
            state = new_state or rec.state
            if state in ('spa_signed', 'registered', 'waiting_handover'):
                rec._offplan_reg_on_activation()
            elif state == 'cancelled':
                rec._offplan_reg_on_contract_cancelled()
            else:
                rec._offplan_reg_sync_required()
        return res

    # ==================================================================
    # Helpers
    # ==================================================================
    def _offplan_reg_apply_reference(self):
        self.ensure_one()
        if not self.offplan_reg_application_ref:
            self.offplan_reg_application_ref = self.env['ir.sequence'].next_by_code(
                'sgc_offplan_registration.application') or False

    def _offplan_reg_users(self, xmlid):
        group = self.env.ref(xmlid, raise_if_not_found=False)
        if not group:
            return self.env['res.users']
        return group.all_user_ids if 'all_user_ids' in group._fields else group.user_ids

    def _offplan_reg_is_manager(self):
        return self.env.user.has_group(MANAGER_GROUP)

    def _offplan_reg_write(self, vals):
        return self.with_context(offplan_reg_syncing=True).write(vals)

    def _offplan_reg_sync_required(self):
        for rec in self:
            status = rec.offplan_reg_status
            if rec.offplan_reg_required and status == 'not_required':
                rec._offplan_reg_write({'offplan_reg_status': 'pending'})
            elif not rec.offplan_reg_required and status in ('not_required', 'pending'):
                rec._offplan_reg_write({'offplan_reg_status': 'not_required'})

    def _offplan_reg_on_activation(self):
        self.ensure_one()
        if self.offplan_reg_required and self.offplan_reg_status == 'not_required':
            self._offplan_reg_write({'offplan_reg_status': 'pending'})
        elif not self.offplan_reg_required and self.offplan_reg_status in (
                'not_required', 'pending'):
            self._offplan_reg_write({'offplan_reg_status': 'not_required'})
        self._offplan_reg_ensure_manager_activity()

    def _offplan_reg_on_contract_cancelled(self):
        self.ensure_one()
        if self.offplan_reg_status in ('pending', 'submitted', 'issued', 'rejected'):
            self._offplan_reg_write({
                'offplan_reg_status': 'cancelled',
                'offplan_reg_cancel_reason': self.offplan_reg_cancel_reason
                or _('Contract cancelled.'),
            })

    def _offplan_reg_activity(self, prefix, users, summary, note=None, deadline=None):
        self.ensure_one()
        stale = self.activity_ids.filtered(
            lambda a: a.summary and a.summary.startswith(prefix))
        stale.unlink()
        for user in users:
            self.activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                date_deadline=deadline, summary=summary, note=note or summary)

    def _offplan_reg_ensure_manager_activity(self):
        self.ensure_one()
        if not self.offplan_reg_required:
            return
        if self.offplan_reg_deadline_configured:
            return
        managers = self._offplan_reg_users(MANAGER_GROUP)
        if not managers:
            return
        prefix = '[OffPlanReg] Deadline not configured'
        stale = self.activity_ids.filtered(
            lambda a: a.summary and a.summary.startswith(prefix))
        if stale:
            return
        summary = _('%s: %s', prefix, self.name)
        for user in managers:
            self.activity_schedule(
                'mail.mail_activity_data_todo', user_id=user.id,
                summary=summary,
                note=_('The emirate rule for %s is unverified or has no deadline. '
                       'Verify the rule in Off-Plan Registration > Rules.',
                       self.offplan_reg_emirate_id.name or _('this emirate')))

    def _offplan_reg_check_active(self):
        self.ensure_one()
        if not self.offplan_reg_required:
            raise UserError(_('This contract does not require off-plan registration.'))
        if self.offplan_reg_needs_review:
            raise UserError(_('Resolve the off-plan flag and emirate first '
                              '(Needs Review).'))

    # ==================================================================
    # Workflow buttons
    # ==================================================================
    def action_offplan_reg_submit(self):
        for rec in self:
            rec._offplan_reg_check_active()
            if rec.offplan_reg_status != 'pending':
                raise UserError(_('Only a Pending registration can be submitted '
                                  '(current: %s).', rec.offplan_reg_status))
            rec._offplan_reg_write({
                'offplan_reg_status': 'submitted',
                'offplan_reg_submitted_on': fields.Datetime.now(),
            })
            if not rec.offplan_reg_application_ref:
                rec._offplan_reg_apply_reference()
        return True

    def action_offplan_reg_issue(self):
        for rec in self:
            if rec.offplan_reg_status != 'submitted':
                raise UserError(_('Issue is only allowed after Submit '
                                  '(current: %s).', rec.offplan_reg_status))
            if not (rec.offplan_reg_certificate_no and rec.offplan_reg_issue_date
                    and rec.offplan_reg_certificate):
                raise UserError(_('Issuing requires a Certificate No., an Issue Date '
                                  'and the certificate file.'))
            rec._offplan_reg_write({'offplan_reg_status': 'issued'})
        return True

    def action_offplan_reg_convert(self):
        for rec in self:
            if rec.offplan_reg_status != 'issued':
                raise UserError(_('Only an Issued registration can be converted '
                                  '(current: %s).', rec.offplan_reg_status))
            if not rec.property_id.title_deed_number:
                raise UserError(_('Set the unit Title Deed Number before converting '
                                  'to a title deed.'))
            rec._offplan_reg_write({'offplan_reg_status': 'converted'})
        return True

    def action_offplan_reg_reject(self):
        for rec in self:
            if rec.offplan_reg_status not in ACTIVE_STATES:
                raise UserError(_('Only a pending, submitted or issued registration '
                                  'can be rejected.'))
            if not rec.offplan_reg_rejection_reason:
                raise UserError(_('A rejection reason is required.'))
            rec._offplan_reg_write({'offplan_reg_status': 'rejected'})
        return True

    def action_offplan_reg_cancel(self):
        for rec in self:
            if rec.offplan_reg_status not in ACTIVE_STATES:
                raise UserError(_('Only a pending, submitted or issued registration '
                                  'can be cancelled.'))
            if not rec.offplan_reg_cancel_reason:
                raise UserError(_('A cancellation reason is required.'))
            rec._offplan_reg_write({'offplan_reg_status': 'cancelled'})
        return True

    def action_offplan_reg_reset(self):
        if not self._offplan_reg_is_manager():
            raise AccessError(_('Only a Property Manager can reset the registration.'))
        for rec in self:
            if rec.offplan_reg_status not in ('rejected', 'cancelled'):
                raise UserError(_('Only a rejected or cancelled registration can be reset.'))
            rec._offplan_reg_write({
                'offplan_reg_status': 'pending' if rec.offplan_reg_required else 'not_required',
                'offplan_reg_rejection_reason': False,
                'offplan_reg_cancel_reason': False,
            })
        return True

    # ==================================================================
    # Sharing
    # ==================================================================
    def _offplan_reg_certificate_attachment(self):
        self.ensure_one()
        return self.env['ir.attachment'].search([
            ('res_model', '=', 'sale.contract'),
            ('res_field', '=', 'offplan_reg_certificate'),
            ('res_id', '=', self.id),
        ], limit=1)

    def _offplan_reg_recipient_emails(self):
        self.ensure_one()
        emails = []
        if self.buyer_id.email:
            emails.append(self.buyer_id.email)
        joint = self.joint_buyer_id.email or self.joint_buyer_email
        if joint and joint not in emails:
            emails.append(joint)
        return emails

    def action_offplan_reg_share(self):
        for rec in self:
            if rec.offplan_reg_status != 'issued':
                raise UserError(_('Only an Issued certificate can be shared.'))
            attachment = rec._offplan_reg_certificate_attachment()
            if not attachment:
                raise UserError(_('No certificate file is attached.'))
            emails = rec._offplan_reg_recipient_emails()
            now = fields.Datetime.now()
            rec._offplan_reg_write({
                'offplan_reg_portal_visible': True,
                'offplan_reg_shared': True,
                'offplan_reg_last_shared_on': now,
            })
            rec.env['offplan.registration.share.log'].sudo().create({
                'contract_id': rec.id,
                'partner_id': rec.buyer_id.id,
                'request_source': 'staff',
                'requested_on': now,
                'shared_on': now,
                'shared_by': rec.env.user.id,
                'channel': 'email',
                'recipient': ', '.join(emails) or rec.buyer_id.email,
                'status': 'shared',
            })
            template = rec.env.ref(
                'sgc_offplan_registration.mail_template_offplan_reg_certificate_shared',
                raise_if_not_found=False)
            if template and emails:
                template.sudo().send_mail(
                    rec.id, force_send=False, raise_exception=False,
                    email_values={
                        'email_to': ', '.join(emails),
                        'attachment_ids': [(6, 0, [attachment.id])],
                    })
        return True

    def action_offplan_reg_view_share_log(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'sgc_offplan_registration.action_offplan_reg_share_log')
        action['domain'] = [('contract_id', '=', self.id)]
        action['context'] = {'default_contract_id': self.id}
        return action

    # ==================================================================
    # Cron
    # ==================================================================
    @api.model
    def _cron_offplan_registration(self):
        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        contracts = self.search([
            ('offplan_reg_required', '=', True),
            ('offplan_reg_status', 'in', ('pending', 'submitted')),
        ])
        officers = self._offplan_reg_users(OFFICER_GROUP)
        managers = self._offplan_reg_users(MANAGER_GROUP) or officers
        for rec in contracts:
            days_left = rec.offplan_reg_days_left
            if rec.offplan_reg_deadline and days_left in (30, 14, 7, 1):
                rec._offplan_reg_activity(
                    '[OffPlanReg] Reminder', officers or managers,
                    _('[OffPlanReg] Reminder: registration due in %(days)s day(s): %(name)s',
                      days=days_left, name=rec.name),
                    deadline=rec.offplan_reg_deadline)
            if rec.offplan_reg_overdue:
                rec._offplan_reg_activity(
                    '[OffPlanReg] Overdue', managers,
                    _('[OffPlanReg] Overdue by %(days)s day(s): %(name)s',
                      days=-days_left, name=rec.name),
                    deadline=rec.offplan_reg_deadline)
            if (rec.offplan_reg_status == 'submitted' and rec.offplan_reg_submitted_on
                    and (now - rec.offplan_reg_submitted_on).days > 30):
                rec._offplan_reg_activity(
                    '[OffPlanReg] Stale submitted', managers,
                    _('[OffPlanReg] Stale submitted over 30 days: %(name)s',
                      name=rec.name))
        return True
