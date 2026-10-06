import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

PARAM_UPCOMING_DAYS = 'sgc_pdc.upcoming_days'
PARAM_EXTRA_EMAILS = 'sgc_pdc.extra_notify_emails'
DEFAULT_UPCOMING_DAYS = 7
CRON_COMMIT_EVERY = 20


class SgcPdcCheque(models.Model):
    _name = 'sgc.pdc.cheque'
    _description = 'Post-Dated Cheque'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'cheque_date, id'
    _check_company_auto = True

    _amount_positive = models.Constraint(
        'CHECK(amount > 0)', 'The cheque amount must be greater than zero.')
    _cheque_unique = models.Constraint(
        'UNIQUE(cheque_number, bank_name, partner_id, company_id)',
        'This cheque number is already registered for the same bank and party.')

    name = fields.Char(string='Reference', copy=False, readonly=True, default='New', index=True)
    direction = fields.Selection([
        ('inbound', 'Receivable (from tenant / buyer)'),
        ('outbound', 'Payable (to landlord / vendor)'),
    ], string='Direction', required=True, default='inbound', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('registered', 'In Hand'),
        ('deposited', 'Deposited'),
        ('cleared', 'Cleared'),
        ('bounced', 'Bounced'),
        ('returned', 'Returned'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', required=True, copy=False, tracking=True, index=True)

    partner_id = fields.Many2one('res.partner', string='Party', required=True, tracking=True)
    cheque_number = fields.Char(string='Cheque No.', required=True, tracking=True)
    bank_name = fields.Char(string='Drawee Bank', tracking=True)
    received_date = fields.Date(
        string='Received / Issued On', default=fields.Date.context_today, tracking=True,
        help='Date the cheque was received from the customer (receivable) or '
             'handed to the vendor (payable).')
    cheque_date = fields.Date(string='Maturity Date', required=True, tracking=True, index=True)
    amount = fields.Monetary(string='Amount', currency_field='currency_id', required=True,
                             tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                  default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one('res.company', string='Company', required=True,
                                 default=lambda self: self.env.company, index=True)
    journal_id = fields.Many2one(
        'account.journal', string='Bank Journal', check_company=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
        help='Journal used when the cheque is cleared (payment is posted here).')
    user_id = fields.Many2one('res.users', string='Responsible', default=lambda self: self.env.user,
                              tracking=True)

    # --- Integration with property management / accounting ---
    installment_id = fields.Many2one(
        'sale.contract.installment', string='Sale Installment', index=True,
        ondelete='set null', tracking=True)
    sale_contract_id = fields.Many2one('sale.contract', string='Sale Contract', index=True,
                                       ondelete='set null')
    tenancy_id = fields.Many2one('tenancy.details', string='Tenancy', index=True,
                                 ondelete='set null', tracking=True)
    rent_invoice_id = fields.Many2one('rent.invoice', string='Rent Invoice', index=True,
                                      ondelete='set null', tracking=True)
    property_id = fields.Many2one('property.details', string='Property', index=True,
                                  ondelete='set null')
    invoice_id = fields.Many2one(
        'account.move', string='Invoice / Bill', check_company=True, ondelete='set null',
        domain="[('move_type', 'in', ('out_invoice', 'in_invoice', 'out_refund', 'in_refund')),"
               " ('state', '=', 'posted')]",
        help='If set, clearing the cheque registers the payment against this invoice.')
    payment_id = fields.Many2one('account.payment', string='Payment', readonly=True, copy=False)

    deposit_date = fields.Date(string='Deposited On', readonly=True, copy=False, tracking=True)
    clear_date = fields.Date(string='Cleared On', readonly=True, copy=False, tracking=True)
    bounce_date = fields.Date(string='Bounced On', readonly=True, copy=False, tracking=True)
    returned_date = fields.Date(string='Returned On', readonly=True, copy=False, tracking=True)
    bounce_reason = fields.Text(string='Bounce Reason', readonly=True, copy=False)
    notes = fields.Text(string='Notes')

    days_to_maturity = fields.Integer(string='Days to Maturity', compute='_compute_days_to_maturity')
    maturity_status = fields.Selection([
        ('upcoming', 'Upcoming'),
        ('matured', 'Matured'),
        ('na', 'N/A'),
    ], string='Maturity', compute='_compute_days_to_maturity',
        search='_search_maturity_status')

    upcoming_notified = fields.Boolean(copy=False, readonly=True)
    matured_notified = fields.Boolean(copy=False, readonly=True)

    # ------------------------------------------------------------------
    # Computes / constraints / onchanges
    # ------------------------------------------------------------------
    @api.depends('cheque_date', 'state')
    def _compute_days_to_maturity(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if rec.cheque_date:
                rec.days_to_maturity = (rec.cheque_date - today).days
            else:
                rec.days_to_maturity = 0
            if rec.state in ('registered', 'deposited') and rec.cheque_date:
                rec.maturity_status = 'matured' if rec.cheque_date <= today else 'upcoming'
            else:
                rec.maturity_status = 'na'

    def _search_maturity_status(self, operator, value):
        if operator not in ('=', '!=', 'in', 'not in'):
            raise UserError(_('Unsupported operator for Maturity.'))
        values = [value] if isinstance(value, str) or not value or not hasattr(value, '__iter__') \
            else list(value)
        today = fields.Date.context_today(self)
        open_states = ('registered', 'deposited')
        parts = {
            'matured': [('state', 'in', open_states), ('cheque_date', '<=', today)],
            'upcoming': [('state', 'in', open_states), ('cheque_date', '>', today)],
            'na': ['|', ('state', 'not in', open_states), ('cheque_date', '=', False)],
        }
        wanted = [Domain(parts[v]) for v in values if v in parts]
        domain = Domain.OR(wanted) if wanted else Domain.FALSE
        return ~domain if operator in ('!=', 'not in') else domain

    @api.onchange('installment_id')
    def _onchange_installment_id(self):
        inst = self.installment_id
        if not inst:
            return
        contract = inst.contract_id
        self.direction = 'inbound'
        self.sale_contract_id = contract
        self.property_id = contract.property_id
        self.partner_id = contract.buyer_id
        self.invoice_id = inst.invoice_id
        self.cheque_date = inst.due_date
        self.amount = inst.amount
        self.tenancy_id = False
        self.rent_invoice_id = False

    @api.onchange('tenancy_id')
    def _onchange_tenancy_id(self):
        ten = self.tenancy_id
        if not ten or self.installment_id:
            return
        self.direction = 'inbound'
        self.property_id = ten.property_id
        self.partner_id = ten.tenant_id
        if not self.amount:
            self.amount = ten.rent_amount

    @api.onchange('rent_invoice_id')
    def _onchange_rent_invoice_id(self):
        ri = self.rent_invoice_id
        if not ri:
            return
        self.direction = 'inbound'
        self.tenancy_id = ri.tenancy_id
        self.property_id = ri.tenancy_id.property_id
        self.partner_id = ri.tenant_id or ri.customer_id or ri.tenancy_id.tenant_id
        self.invoice_id = ri.invoice_id or ri.rent_invoice_id
        self.cheque_date = ri.due_date
        self.amount = ri.amount or ri.rent_amount

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('sgc.pdc.cheque') or 'New'
            # Keep the denormalised links consistent when only the leaf was given.
            if vals.get('installment_id') and not vals.get('sale_contract_id'):
                inst = self.env['sale.contract.installment'].browse(vals['installment_id'])
                vals['sale_contract_id'] = inst.contract_id.id
                vals.setdefault('property_id', inst.contract_id.property_id.id)
        return super().create(vals_list)

    def write(self, vals):
        if {'cheque_date', 'amount'} & set(vals):
            vals.setdefault('upcoming_notified', False)
            vals.setdefault('matured_notified', False)
        return super().write(vals)

    def unlink(self):
        if any(rec.state not in ('draft', 'cancelled') for rec in self):
            raise UserError(_('Only draft or cancelled cheques can be deleted.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------
    def _check_state(self, allowed):
        for rec in self:
            if rec.state not in allowed:
                raise UserError(_('Cheque %(name)s cannot do this from status "%(state)s".',
                                  name=rec.name,
                                  state=dict(rec._fields['state'].selection).get(rec.state)))

    def action_register(self):
        self._check_state(('draft',))
        self.write({'state': 'registered'})

    def action_deposit(self):
        self._check_state(('registered',))
        for rec in self:
            if rec.direction == 'inbound' and not rec.journal_id:
                raise UserError(_('Select the bank journal before depositing cheque %s.', rec.name))
        self.write({'state': 'deposited', 'deposit_date': fields.Date.context_today(self)})

    def action_clear(self):
        """Mark as cleared and book the payment (against the invoice when linked)."""
        self._check_state(('registered', 'deposited'))
        for rec in self:
            if not rec.journal_id:
                raise UserError(_('Select the bank journal before clearing cheque %s.', rec.name))
            payment = rec._create_payment()
            rec.write({
                'state': 'cleared',
                'clear_date': fields.Date.context_today(rec),
                'payment_id': payment.id if payment else False,
            })
            rec.message_post(body=_('Cheque cleared. Payment: %s', payment.display_name if payment else '-'))

    def action_bounce(self):
        self._check_state(('registered', 'deposited'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Bounce Cheque'),
            'res_model': 'sgc.pdc.bounce.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_cheque_id': self.id},
        }

    def _do_bounce(self, reason):
        self._check_state(('registered', 'deposited'))
        for rec in self:
            rec.write({'state': 'bounced', 'bounce_reason': reason,
                       'bounce_date': fields.Date.context_today(rec)})
            rec.message_post(body=_('Cheque bounced. Reason: %s', reason or '-'))
            if rec.user_id:
                rec.activity_schedule(
                    'mail.mail_activity_data_todo', user_id=rec.user_id.id,
                    summary=_('Follow up bounced cheque %s', rec.name),
                    note=_('Contact %(party)s for a replacement cheque or payment.',
                           party=rec.partner_id.display_name))

    def action_return(self):
        self._check_state(('registered', 'bounced'))
        self.write({'state': 'returned', 'returned_date': fields.Date.context_today(self)})

    def action_cancel(self):
        self._check_state(('draft', 'registered', 'bounced', 'returned'))
        self.write({'state': 'cancelled'})

    def action_reset_draft(self):
        self._check_state(('cancelled', 'bounced', 'returned'))
        self.write({'state': 'draft', 'bounce_reason': False, 'bounce_date': False,
                    'returned_date': False, 'deposit_date': False, 'clear_date': False,
                    'upcoming_notified': False, 'matured_notified': False})

    def action_print_receipt(self):
        self.ensure_one()
        return self.env.ref('sgc_pdc_management.action_report_pdc_receipt').report_action(self)

    def action_open_invoice(self):
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_('No invoice linked.'))
        return self.invoice_id._get_records_action()

    def action_open_payment(self):
        self.ensure_one()
        if not self.payment_id:
            raise UserError(_('No payment yet.'))
        return self.payment_id._get_records_action()

    # ------------------------------------------------------------------
    # Accounting
    # ------------------------------------------------------------------
    def _create_payment(self):
        self.ensure_one()
        inv = self.invoice_id
        today = fields.Date.context_today(self)
        memo = _('PDC %(name)s - cheque %(no)s', name=self.name, no=self.cheque_number)
        if inv and inv.state == 'posted' and inv.amount_residual > 0 \
                and inv.payment_state not in ('paid', 'in_payment', 'reversed'):
            wizard = self.env['account.payment.register'].with_context(
                active_model='account.move', active_ids=inv.ids).create({
                    'journal_id': self.journal_id.id,
                    'amount': min(self.amount, inv.amount_residual),
                    'payment_date': today,
                    'communication': memo,
                })
            return wizard._create_payments()[:1]
        payment = self.env['account.payment'].create({
            'payment_type': 'inbound' if self.direction == 'inbound' else 'outbound',
            'partner_type': 'customer' if self.direction == 'inbound' else 'supplier',
            'partner_id': self.partner_id.id,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'journal_id': self.journal_id.id,
            'date': today,
            'memo': memo,
            'company_id': self.company_id.id,
        })
        payment.action_post()
        return payment

    # ------------------------------------------------------------------
    # Notifications (cron)
    # ------------------------------------------------------------------
    @api.model
    def _get_upcoming_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_UPCOMING_DAYS)
        try:
            return max(int(raw), 0) if raw is not False and raw != '' else DEFAULT_UPCOMING_DAYS
        except (TypeError, ValueError):
            return DEFAULT_UPCOMING_DAYS

    @api.model
    def _get_extra_emails(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(PARAM_EXTRA_EMAILS) or ''
        return [e.strip() for e in raw.replace(';', ',').split(',') if e.strip()]

    @api.model
    def _cron_progress(self, processed=0, remaining=None):
        """Commit progress inside a real cron run only (Odoo's own convention). Returns the seconds left
        in the run, 0 meaning "stop, the scheduler will call us again"."""
        if not self.env.context.get('cron_id'):
            return float('inf')
        return self.env['ir.cron']._commit_progress(processed, remaining=remaining)

    @api.model
    def _cron_notify_cheques(self):
        """Daily job. Works in batches and commits as it goes so a large backlog never hits the cron
        time limit: the scheduler runs it again for whatever is left."""
        today = fields.Date.context_today(self)
        horizon = today + timedelta(days=self._get_upcoming_days())
        base = [('state', 'in', ('registered', 'deposited'))]
        upcoming = self.search(base + [
            ('cheque_date', '>', today), ('cheque_date', '<=', horizon),
            ('upcoming_notified', '=', False)], order='cheque_date, id')
        matured = self.search(base + [
            ('cheque_date', '<=', today), ('matured_notified', '=', False)], order='cheque_date, id')
        jobs = [(rec, 'sgc_pdc_management.mail_template_pdc_matured', 'matured_notified', _('Matured cheque'))
                for rec in matured]
        jobs += [(rec, 'sgc_pdc_management.mail_template_pdc_upcoming', 'upcoming_notified', _('Upcoming cheque'))
                 for rec in upcoming]
        extra = self._get_extra_emails()
        templates = {}
        if not self._cron_progress(remaining=len(jobs)):
            return True                                   # no time left in this run, continue next time
        done = pending = 0
        for rec, xmlid, flag, summary in jobs:
            template = templates.setdefault(xmlid, self.env.ref(xmlid, raise_if_not_found=False))
            try:
                with self.env.cr.savepoint():
                    rec._notify_one(template, extra, flag, summary)
                done += 1
            except Exception:  # one bad record must not stop the run
                _logger.exception('PDC notification failed for %s', rec.display_name)
            pending += 1
            if pending >= CRON_COMMIT_EVERY:                # committing is costly: do it in chunks
                if not self._cron_progress(pending):
                    _logger.info('PDC notifications out of time; the scheduler will continue.')
                    pending = 0
                    break
                pending = 0
        if pending:
            self._cron_progress(pending)
        _logger.info('PDC notifications sent: %s of %s', done, len(jobs))
        return True

    def _notify_one(self, template, extra_emails, flag_field, summary):
        self.ensure_one()
        user = self.user_id
        note = _('%(summary)s %(name)s: %(amount)s from/to %(party)s, maturity %(date)s.',
                 summary=summary, name=self.name, party=self.partner_id.display_name,
                 amount=self.currency_id.format(self.amount), date=self.cheque_date)
        if user:
            # Odoo inbox notification + to-do activity for the responsible user.
            self.message_post(body=note, partner_ids=user.partner_id.ids,
                              subtype_xmlid='mail.mt_note', message_type='notification')
            self.activity_schedule('mail.mail_activity_data_todo', date_deadline=self.cheque_date,
                                   user_id=user.id, summary=summary, note=note)
        if template:
            email_to = ','.join(
                ([user.email_formatted] if user.email else []) + extra_emails)
            if email_to:
                template.send_mail(self.id, force_send=False,
                                   email_values={'email_to': email_to})
        self.write({flag_field: True})
