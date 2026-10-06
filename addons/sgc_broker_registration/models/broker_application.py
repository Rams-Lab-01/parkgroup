import hashlib
import hmac
import logging
import re
import secrets
from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from .document_type import EMIRATES

_logger = logging.getLogger(__name__)

CODE_TTL_MINUTES = 10
CODE_MAX_ATTEMPTS = 5
CODE_COOLDOWN_SECONDS = 60
CODE_MAX_SENDS_PER_HOUR = 5
MAX_APPLICATIONS_PER_EMAIL_PER_DAY = 3
PARAM_AGREEMENT_MONTHS = 'sgc_broker.agreement_validity_months'
PARAM_PRE_DAYS = 'sgc_broker.expiry_pre_days'
PARAM_REPEAT_DAYS = 'sgc_broker.expiry_repeat_days'
PARAM_EXTRA_EMAILS = 'sgc_broker.extra_notify_emails'
DEFAULT_AGREEMENT_MONTHS = 12
DEFAULT_PRE_DAYS = 5
DEFAULT_REPEAT_DAYS = 15
CRON_COMMIT_EVERY = 10
EDITABLE_STATES = ('draft', 'verified', 'needs_info')

CONTROL_CHARS_RE = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
MAX_LEN = {'street': 300}
DEFAULT_MAX_LEN = 200

EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')


# ----------------------------------------------------------------------
# Field validators (module level so the portal and the model share them)
# ----------------------------------------------------------------------
def normalize_email(value):
    value = (value or '').strip().lower()
    if not EMAIL_RE.match(value):
        raise ValidationError(_('Enter a valid email address.'))
    return value


def normalize_phone(value, label=None):
    label = label or _('Phone')
    digits = re.sub(r'\D', '', value or '')
    if digits.startswith('00'):
        digits = digits[2:]
    if not 9 <= len(digits) <= 15:
        raise ValidationError(_('%s must contain 9 to 15 digits (include the country code, e.g. +971 50 123 4567).', label))
    if len(digits) == 10 and digits.startswith('05'):   # local UAE mobile 05x xxx xxxx
        digits = '971' + digits[1:]
    return '+' + digits


def normalize_emirates_id(value):
    digits = re.sub(r'[\s\-]', '', value or '')
    if not re.fullmatch(r'784\d{12}', digits):
        raise ValidationError(_('Emirates ID must be 15 digits starting with 784 (784-YYYY-NNNNNNN-C).'))
    return '%s-%s-%s-%s' % (digits[:3], digits[3:7], digits[7:14], digits[14:])


def normalize_trn(value):
    digits = re.sub(r'\s', '', value or '')
    if not re.fullmatch(r'\d{15}', digits):
        raise ValidationError(_('The VAT Tax Registration Number (TRN) must be exactly 15 digits.'))
    return digits


def normalize_iban(value):
    iban = re.sub(r'\s', '', value or '').upper()
    if not re.fullmatch(r'[A-Z]{2}\d{2}[A-Z0-9]{10,30}', iban):
        raise ValidationError(_('Enter a valid IBAN.'))
    if iban.startswith('AE') and len(iban) != 23:
        raise ValidationError(_('A UAE IBAN has 23 characters (AE + 21 digits).'))
    rearranged = iban[4:] + iban[:4]
    numeric = ''.join(str(int(ch, 36)) for ch in rearranged)
    if int(numeric) % 97 != 1:
        raise ValidationError(_('The IBAN check digits are invalid. Please re-check the number.'))
    return iban


def normalize_registration_no(value, label):
    value = re.sub(r'\s', '', value or '')
    if not re.fullmatch(r'\d{3,10}', value):
        raise ValidationError(_('%s must be 3 to 10 digits.', label))
    return value


class SgcBrokerApplication(models.Model):
    _name = 'sgc.broker.application'
    _description = 'Broker Registration Application'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'
    _rec_name = 'name'

    name = fields.Char(string='Reference', default='New', copy=False, readonly=True, index=True)
    access_token = fields.Char(copy=False, index=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Email not verified'),
        ('verified', 'Collecting documents'),
        ('submitted', 'Submitted'),
        ('in_review', 'In review'),
        ('needs_info', 'More information needed'),
        ('approved', 'Registered'),
        ('rejected', 'Rejected'),
    ], default='draft', required=True, tracking=True, copy=False, index=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True)

    # --- Applicant ---
    applicant_type = fields.Selection([
        ('individual', 'Individual broker'),
        ('company', 'Brokerage company'),
    ], required=True, default='company', tracking=True)
    emirate = fields.Selection(EMIRATES, string='Regulator / Emirate', required=True, tracking=True)
    company_name = fields.Char(string='Company / Trade Name')
    full_name = fields.Char(string='Full Name (as in passport)', required=True)
    email = fields.Char(required=True, index=True, tracking=True)
    phone = fields.Char(string='Mobile', required=True)
    nationality_id = fields.Many2one('res.country', string='Nationality')
    street = fields.Char(string='Office Address')
    city = fields.Char()
    po_box = fields.Char(string='P.O. Box')
    website = fields.Char()

    # --- Registrations / compliance identifiers ---
    trade_license_no = fields.Char(string='Trade Licence No.')
    trade_license_authority = fields.Char(string='Licensing Authority')
    trade_license_issue_date = fields.Date()
    trade_license_expiry = fields.Date()
    orn = fields.Char(string='Brokerage Office No. (ORN)')
    brn = fields.Char(string='Broker Registration No. (BRN)')
    regulator_expiry = fields.Date(string='Regulator Card / Registration Expiry')
    vat_trn = fields.Char(string='VAT TRN')
    goaml_id = fields.Char(string='goAML Registration ID')
    emirates_id = fields.Char(string='Emirates ID (applicant / signatory)')
    passport_no = fields.Char(string='Passport No.')
    signatory_name = fields.Char(string='Authorised Signatory')
    signatory_title = fields.Char(string='Signatory Title')

    # --- Bank ---
    bank_name = fields.Char()
    iban = fields.Char(string='IBAN')
    account_holder = fields.Char()

    # --- Email verification ---
    email_verified = fields.Boolean(readonly=True, copy=False, tracking=True)
    verified_at = fields.Datetime(readonly=True, copy=False)
    code_hash = fields.Char(copy=False, groups='base.group_system')
    code_expiry = fields.Datetime(copy=False)
    code_attempts = fields.Integer(copy=False)
    code_last_sent = fields.Datetime(copy=False)
    code_window_start = fields.Datetime(copy=False)
    code_sends_in_window = fields.Integer(copy=False)

    # --- Declarations / e-agreement ---
    accept_terms = fields.Boolean(string='Accepts brokerage agreement terms', copy=False)
    accept_aml = fields.Boolean(string='AML / sanctions declaration', copy=False)
    accept_accuracy = fields.Boolean(string='Information is true and complete', copy=False)
    declared_name = fields.Char(string='Typed signature', copy=False)
    declared_at = fields.Datetime(copy=False)
    declared_ip = fields.Char(copy=False)
    create_ip = fields.Char(copy=False)

    # --- Documents ---
    document_ids = fields.One2many('sgc.broker.application.document', 'application_id')
    missing_type_ids = fields.Many2many('sgc.broker.document.type', compute='_compute_missing_types')
    docs_complete = fields.Boolean(compute='_compute_missing_types')

    # --- Review ---
    partner_id = fields.Many2one('res.partner', string='Contact', readonly=True, copy=False, tracking=True)
    reviewer_id = fields.Many2one('res.users', string='Reviewer', copy=False, tracking=True)
    reviewed_at = fields.Datetime(copy=False)
    review_note = fields.Text(string='Reviewer note to applicant', copy=False)
    submitted_at = fields.Datetime(copy=False)
    agreement_start = fields.Date(string='Agreement Start', readonly=True, copy=False, tracking=True)
    agreement_expiry = fields.Date(string='Agreement Expiry', copy=False, tracking=True,
                                   help='Set to one year after approval; extended on renewal.')
    expiry_tracker_ids = fields.One2many('sgc.broker.expiry.tracker', 'application_id', string='Expiry Monitor')

    _one_open_per_email = models.UniqueIndex(
        "(email) WHERE state != 'rejected'", 'An application for this email address is already in progress.')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    def _required_types(self):
        self.ensure_one()
        types = self.env['sgc.broker.document.type'].sudo().search([('required', '=', True)])
        return types.filtered(lambda t: t._applies_to(self.applicant_type, self.emirate))

    def _applicable_types(self):
        self.ensure_one()
        types = self.env['sgc.broker.document.type'].sudo().search([])
        return types.filtered(lambda t: t._applies_to(self.applicant_type, self.emirate))

    @api.depends('document_ids.state', 'document_ids.type_id', 'document_ids.expiry_date',
                 'applicant_type', 'emirate')
    def _compute_missing_types(self):
        today = fields.Date.context_today(self)
        for rec in self:
            if not rec.applicant_type or not rec.emirate:
                rec.missing_type_ids = False
                rec.docs_complete = False
                continue
            valid = rec.document_ids.filtered(
                lambda d: d.state != 'rejected' and not (d.type_id.has_expiry and (
                    not d.expiry_date or d.expiry_date <= today))).type_id
            missing = rec._required_types() - valid
            rec.missing_type_ids = missing
            rec.docs_complete = not missing

    # ------------------------------------------------------------------
    # CRUD / validation
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('name', 'New')
            if vals['name'] == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('sgc.broker.application') or 'New'
            vals.setdefault('access_token', secrets.token_urlsafe(32))
        return super().create(vals_list)

    @api.model
    def _clean_vals(self, vals):
        """Normalise and validate every identifier the portal / backend can send."""
        out = dict(vals)
        if out.get('email'):
            out['email'] = normalize_email(out['email'])
        if out.get('phone'):
            out['phone'] = normalize_phone(out['phone'], _('Mobile'))
        if out.get('emirates_id'):
            out['emirates_id'] = normalize_emirates_id(out['emirates_id'])
        if out.get('vat_trn'):
            out['vat_trn'] = normalize_trn(out['vat_trn'])
        if out.get('iban'):
            out['iban'] = normalize_iban(out['iban'])
        if out.get('orn'):
            out['orn'] = normalize_registration_no(out['orn'], _('ORN'))
        if out.get('brn'):
            out['brn'] = normalize_registration_no(out['brn'], _('BRN'))
        for key in list(out):
            if isinstance(out[key], str):
                out[key] = out[key].strip()
                if CONTROL_CHARS_RE.search(out[key]):
                    raise ValidationError(_('The field "%s" contains invalid characters.', key))
                if len(out[key]) > MAX_LEN.get(key, DEFAULT_MAX_LEN):
                    raise ValidationError(_('The field "%(field)s" is too long (maximum %(max)s characters).',
                                            field=key, max=MAX_LEN.get(key, DEFAULT_MAX_LEN)))
        return out

    @api.constrains('trade_license_issue_date', 'trade_license_expiry')
    def _check_licence_dates(self):
        for rec in self:
            if rec.trade_license_issue_date and rec.trade_license_expiry \
                    and rec.trade_license_expiry < rec.trade_license_issue_date:
                raise ValidationError(_('The licence expiry date cannot be before its issue date.'))

    def unlink(self):
        if any(rec.state in ('approved',) for rec in self):
            raise UserError(_('An approved application cannot be deleted.'))
        return super().unlink()

    # ------------------------------------------------------------------
    # Email verification
    # ------------------------------------------------------------------
    def _hash_code(self, code):
        secret = self.env['ir.config_parameter'].sudo().get_param('database.secret') or ''
        return hmac.new(secret.encode(), ('%s:%s' % (self.id, code)).encode(), hashlib.sha256).hexdigest()

    def _lock_row(self):
        """Serialise concurrent requests on one application (code requests, guesses, uploads).

        Acquires a row-level lock via SELECT ... FOR UPDATE so concurrent requests on the same
        application are serialized. Under PostgreSQL REPEATABLE READ, the second transaction
        blocks until the first commits, then re-reads the fresh values (or retries on a
        serialization failure). This prevents lost updates on code_attempts / code_hash."""
        self.ensure_one()
        self.env.cr.execute('SELECT id FROM sgc_broker_application WHERE id = %s FOR UPDATE', [self.id])
        self.invalidate_recordset()

    def action_send_code(self):
        """Generate and email a fresh 6-digit code. Returns (status, wait_seconds)."""
        self.ensure_one()
        self = self.sudo()
        self._lock_row()
        now = fields.Datetime.now()
        if self.email_verified:
            return 'verified', 0
        if self.code_last_sent:
            wait = CODE_COOLDOWN_SECONDS - int((now - self.code_last_sent).total_seconds())
            if wait > 0:
                return 'cooldown', wait
        in_window = (self.code_window_start and now - self.code_window_start < timedelta(hours=1))
        sends = self.code_sends_in_window if in_window else 0
        if sends >= CODE_MAX_SENDS_PER_HOUR:
            return 'limit', 0
        code = '%06d' % secrets.randbelow(10 ** 6)
        self.write({
            'code_hash': self._hash_code(code),
            'code_expiry': now + timedelta(minutes=CODE_TTL_MINUTES),
            'code_attempts': 0,
            'code_last_sent': now,
            'code_window_start': self.code_window_start if in_window else now,
            'code_sends_in_window': sends + 1,
        })
        template = self.env.ref('sgc_broker_registration.mail_template_verification_code')
        template.with_context(code=code, ttl=CODE_TTL_MINUTES).send_mail(
            self.id, force_send=False, raise_exception=False)
        return 'ok', 0

    def verify_code(self, code):
        """Returns 'ok', 'bad', 'expired', 'locked' or 'none'."""
        self.ensure_one()
        self = self.sudo()
        self._lock_row()
        if self.email_verified:
            return 'ok'
        if not self.code_hash:
            return 'none'
        if self.code_attempts >= CODE_MAX_ATTEMPTS:
            return 'locked'
        if fields.Datetime.now() > self.code_expiry:
            return 'expired'
        code = re.sub(r'\D', '', code or '')
        self.code_attempts += 1
        if not hmac.compare_digest(self._hash_code(code), self.code_hash):
            return 'locked' if self.code_attempts >= CODE_MAX_ATTEMPTS else 'bad'
        self.write({'email_verified': True, 'verified_at': fields.Datetime.now(),
                    'code_hash': False, 'code_expiry': False, 'state': 'verified'})
        self.message_post(body=_('Email address %s verified by the applicant.', self.email))
        return 'ok'

    # ------------------------------------------------------------------
    # Applicant submission
    # ------------------------------------------------------------------
    def _validate_for_submit(self):
        self.ensure_one()
        errors = []
        if not self.email_verified:
            errors.append(_('Verify your email address first.'))
        if self.state not in ('verified', 'needs_info'):
            errors.append(_('This application can no longer be changed.'))
        if self.applicant_type == 'company':
            for field, label in (('company_name', _('Company name')), ('trade_license_no', _('Trade licence number')),
                                 ('trade_license_expiry', _('Trade licence expiry')),
                                 ('orn', _('Brokerage office number (ORN)')),
                                 ('signatory_name', _('Authorised signatory')),
                                 ('emirates_id', _('Emirates ID'))):
                if not self[field]:
                    errors.append(_('%s is required.', label))
        else:
            for field, label in (('brn', _('Broker registration number (BRN)')),
                                 ('emirates_id', _('Emirates ID')), ('passport_no', _('Passport number'))):
                if not self[field]:
                    errors.append(_('%s is required.', label))
        today = fields.Date.context_today(self)
        if self.trade_license_expiry and self.trade_license_expiry <= today:
            errors.append(_('The trade licence has expired.'))
        if self.regulator_expiry and self.regulator_expiry <= today:
            errors.append(_('The regulator registration / card has expired.'))
        for missing in self.missing_type_ids:
            errors.append(_('Missing required document: %s', missing.name))
        if not (self.accept_terms and self.accept_aml and self.accept_accuracy):
            errors.append(_('Tick all three declarations.'))
        if not (self.declared_name or '').strip():
            errors.append(_('Type your full name as your electronic signature.'))
        return errors

    def action_submit(self, ip=None):
        self.ensure_one()
        self = self.sudo()
        errors = self._validate_for_submit()
        if errors:
            raise ValidationError('\n'.join(errors))
        self.write({'state': 'submitted', 'submitted_at': fields.Datetime.now(),
                    'declared_at': fields.Datetime.now(), 'declared_ip': ip or False})
        self.message_post(body=_('Application submitted by %(name)s (e-signature) from IP %(ip)s.',
                                 name=self.declared_name, ip=ip or '-'))
        self._notify_officers(_('New broker application %s needs review.', self.name))
        self.env.ref('sgc_broker_registration.mail_template_submitted').sudo().send_mail(
            self.id, force_send=False, raise_exception=False)
        return True

    def _officers(self):
        group = self.env.ref('sgc_broker_registration.group_broker_officer')
        return (group.all_user_ids if 'all_user_ids' in group._fields else group.user_ids)

    def _notify_officers(self, summary):
        for rec in self:
            for user in rec._officers():
                rec.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                      summary=summary, note=summary)

    # ------------------------------------------------------------------
    # Review workflow (back office)
    # ------------------------------------------------------------------
    def _check_state(self, allowed):
        for rec in self:
            if rec.state not in allowed:
                raise UserError(_('Application %(name)s cannot do this in status "%(state)s".',
                                  name=rec.name, state=dict(rec._fields['state'].selection).get(rec.state)))

    def action_start_review(self):
        self._check_state(('submitted', 'needs_info'))
        self.write({'state': 'in_review', 'reviewer_id': self.env.user.id})

    def action_approve(self):
        self._check_state(('submitted', 'in_review'))
        for rec in self:
            accepted_types = rec.document_ids.filtered(lambda d: d.state == 'accepted').type_id
            if not rec._required_types() <= accepted_types:
                raise UserError(_('Accept every required document before approving %s.', rec.name))
            today = fields.Date.context_today(rec)
            rec.write({'agreement_start': today,
                       'agreement_expiry': today + relativedelta(months=rec._agreement_months())})
            partner = rec._map_to_partner()
            rec.write({'state': 'approved', 'partner_id': partner.id, 'reviewer_id': self.env.user.id,
                       'reviewed_at': fields.Datetime.now()})
            rec.sudo()._sync_expiry_trackers()
            rec.sudo()._refresh_broker_status()
            rec.message_post(body=_('Registered. Agreement valid until %(date)s. Mapped to contact %(partner)s.',
                                    date=rec.agreement_expiry, partner=partner.display_name))
            rec.env.ref('sgc_broker_registration.mail_template_approved').sudo().send_mail(
                rec.id, force_send=False, raise_exception=False)
            rec.activity_unlink(['mail.mail_activity_data_todo'])

    def action_open_reject_wizard(self):
        self._check_state(('submitted', 'in_review'))
        return self._wizard('reject')

    def action_open_info_wizard(self):
        self._check_state(('submitted', 'in_review'))
        return self._wizard('info')

    def _wizard(self, mode):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Reject application') if mode == 'reject' else _('Request more information'),
            'res_model': 'sgc.broker.reject.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_application_id': self.id, 'default_mode': mode},
        }

    def _do_reject(self, reason):
        self._check_state(('submitted', 'in_review'))
        self.write({'state': 'rejected', 'review_note': reason, 'reviewer_id': self.env.user.id,
                    'reviewed_at': fields.Datetime.now()})
        self.message_post(body=_('Rejected: %s', reason))
        self.env.ref('sgc_broker_registration.mail_template_rejected').sudo().send_mail(
            self.id, force_send=False, raise_exception=False)

    def _do_request_info(self, reason):
        self._check_state(('submitted', 'in_review'))
        self.write({'state': 'needs_info', 'review_note': reason, 'reviewer_id': self.env.user.id})
        self.message_post(body=_('More information requested: %s', reason))
        self.env.ref('sgc_broker_registration.mail_template_needs_info').sudo().send_mail(
            self.id, force_send=False, raise_exception=False)

    def action_reset_to_review(self):
        self._check_state(('rejected',))
        self.write({'state': 'in_review'})

    def action_open_partner(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Not mapped to a contact yet.'))
        return self.partner_id._get_records_action()

    # ------------------------------------------------------------------
    # Mapping to Contacts
    # ------------------------------------------------------------------
    def _find_existing_partner(self):
        self.ensure_one()
        Partner = self.env['res.partner'].sudo()
        if self.partner_id:
            return self.partner_id
        for field, value in (('sgc_broker_orn', self.orn), ('sgc_broker_brn', self.brn),
                             ('sgc_trade_license_no', self.trade_license_no), ('vat', self.vat_trn)):
            if value and field in Partner._fields:
                found = Partner.search([(field, '=', value)], limit=1)
                if found:
                    return found
        found = Partner.search([('email', '=ilike', self.email),
                                ('is_company', '=', self.applicant_type == 'company')], limit=1)
        return found

    def _partner_vals(self):
        self.ensure_one()
        country = self.env.ref('base.ae')
        vals = {
            'name': self.company_name if self.applicant_type == 'company' else self.full_name,
            'is_company': self.applicant_type == 'company',
            'email': self.email,
            'phone': self.phone,
            'street': self.street,
            'city': self.city,
            'zip': self.po_box,
            'website': self.website,
            'country_id': country.id,
            'vat': self.vat_trn or False,
            'category_id': [(4, self.env.ref('sgc_broker_registration.partner_category_registered_broker').id)],
            'sgc_is_broker': True,
            'sgc_broker_type': self.applicant_type,
            'sgc_broker_status': 'registered',
            'sgc_agreement_expiry': self.agreement_expiry or False,
            'sgc_regulator': self.emirate,
            'sgc_broker_orn': self.orn or False,
            'sgc_broker_brn': self.brn or False,
            'sgc_trade_license_no': self.trade_license_no or False,
            'sgc_trade_license_authority': self.trade_license_authority or False,
            'sgc_trade_license_expiry': self.trade_license_expiry or False,
            'sgc_regulator_expiry': self.regulator_expiry or False,
            'sgc_goaml_id': self.goaml_id or False,
            'sgc_emirates_id': self.emirates_id or False,
            'sgc_passport_no': self.passport_no or False,
            'sgc_broker_application_id': self.id,
        }
        if self.nationality_id and self.applicant_type == 'individual':
            vals['sgc_nationality_id'] = self.nationality_id.id
        if 'user_type' in self.env['res.partner']._fields:       # property management integration
            vals['user_type'] = 'broker'
        return vals

    def _map_to_partner(self):
        """Create / update the contact, its signatory contact, bank account and documents."""
        self.ensure_one()
        Partner = self.env['res.partner'].sudo()
        vals = self._partner_vals()
        partner = self._find_existing_partner()
        if partner:
            partner.write(vals)
        else:
            partner = Partner.create(vals)
        if self.applicant_type == 'company' and self.signatory_name:
            contact = Partner.search([('parent_id', '=', partner.id), ('name', '=', self.signatory_name)], limit=1)
            contact_vals = {'name': self.signatory_name, 'parent_id': partner.id, 'type': 'contact',
                            'function': self.signatory_title or False, 'email': self.email,
                            'phone': self.phone, 'sgc_emirates_id': self.emirates_id or False}
            if contact:
                contact.write(contact_vals)
            else:
                Partner.create(contact_vals)
        if self.iban:
            bank = self.env['res.partner.bank'].sudo().search(
                [('partner_id', '=', partner.id), ('sanitized_acc_number', '=', self.iban)], limit=1)
            if not bank:
                try:
                    with self.env.cr.savepoint():
                        self.env['res.partner.bank'].sudo().create({
                            'partner_id': partner.id, 'acc_number': self.iban,
                            'acc_holder_name': self.account_holder or partner.name})
                except Exception:   # a bank-format rule must never block an approval
                    _logger.warning('Bank account %s could not be created for %s', self.iban, partner.name)
        Attachment = self.env['ir.attachment'].sudo()
        for doc in self.document_ids.filtered(lambda d: d.state == 'accepted'):
            exists = Attachment.search_count([
                ('res_model', '=', 'res.partner'), ('res_id', '=', partner.id),
                ('name', '=', '%s - %s' % (doc.type_id.name, doc.filename))])
            if not exists:
                Attachment.create({
                    'name': '%s - %s' % (doc.type_id.name, doc.filename),
                    'res_model': 'res.partner', 'res_id': partner.id,
                    'datas': doc.file, 'description': doc.expiry_date and
                    _('Expires %s', doc.expiry_date) or False})
        return partner

    # ------------------------------------------------------------------
    # Expiry monitoring: agreement, licences, expiring documents
    # ------------------------------------------------------------------
    @api.model
    def _param_int(self, key, default, minimum=0):
        raw = self.env['ir.config_parameter'].sudo().get_param(key)
        try:
            return max(int(raw), minimum) if raw not in (False, None, '') else default
        except (TypeError, ValueError):
            return default

    def _agreement_months(self):
        return self._param_int(PARAM_AGREEMENT_MONTHS, DEFAULT_AGREEMENT_MONTHS, minimum=1)

    def _expiry_items(self):
        """Everything of this registered broker that can lapse: [(key, label, date)]."""
        self.ensure_one()
        items = [
            ('agreement', _('Brokerage agreement'), self.agreement_expiry),
            ('trade_license', _('Trade licence'), self.trade_license_expiry),
            ('regulator', _('Regulator registration / broker card'), self.regulator_expiry),
        ]
        for doc in self.document_ids.filtered(lambda d: d.state == 'accepted' and d.expiry_date):
            items.append(('doc%s' % doc.id, doc.type_id.name, doc.expiry_date))
        return [item for item in items if item[2]]

    def _sync_expiry_trackers(self):
        """Create / update / remove the tracker rows so they mirror the current expiry dates."""
        Tracker = self.env['sgc.broker.expiry.tracker'].sudo()
        for rec in self:
            items = {key: (label, date) for key, label, date in rec._expiry_items()}
            existing = {t.key: t for t in rec.expiry_tracker_ids}
            for key, (label, date) in items.items():
                tracker = existing.get(key)
                if not tracker:
                    Tracker.create({'application_id': rec.id, 'key': key, 'label': label, 'expiry_date': date})
                elif tracker.expiry_date != date or tracker.label != label:
                    # renewed or corrected: start the reminder cycle again
                    vals = {'label': label, 'expiry_date': date}
                    if tracker.expiry_date != date:
                        vals.update({'pre_alert_date': False, 'last_alert_date': False})
                    tracker.write(vals)
            for key, tracker in existing.items():
                if key not in items:
                    tracker.unlink()

    def _refresh_broker_status(self):
        """Contact status: Registered while agreement and licences are valid, otherwise Expired."""
        today = fields.Date.context_today(self)
        for rec in self.filtered(lambda r: r.state == 'approved' and r.partner_id):
            critical = [d for d in (rec.agreement_expiry, rec.trade_license_expiry, rec.regulator_expiry) if d]
            lapsed = any(d <= today for d in critical)
            partner = rec.partner_id.sudo()
            if partner.sgc_broker_status != 'suspended':
                new = 'expired' if lapsed else 'registered'
                if partner.sgc_broker_status != new:
                    partner.sgc_broker_status = new
            if partner.sgc_agreement_expiry != rec.agreement_expiry:
                partner.sgc_agreement_expiry = rec.agreement_expiry

    def write(self, vals):
        res = super().write(vals)
        if {'agreement_expiry', 'trade_license_expiry', 'regulator_expiry'} & set(vals):
            approved = self.filtered(lambda r: r.state == 'approved')
            approved.sudo()._sync_expiry_trackers()
            approved.sudo()._refresh_broker_status()
        return res

    def action_renew_agreement(self):
        self._check_state(('approved',))
        today = fields.Date.context_today(self)
        for rec in self:
            base = max(rec.agreement_expiry or today, today)
            rec.write({'agreement_start': today,
                       'agreement_expiry': base + relativedelta(months=rec._agreement_months())})
            rec.message_post(body=_('Agreement renewed until %s.', rec.agreement_expiry))

    @api.model
    def _extra_notify_emails(self):
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
    def _cron_check_expiries(self):
        """Daily job. For the PRE_DAYS days before an expiry date it reminds every day; on the
        expiry date (first day of expiration) it sends the expired notice, then repeats every
        REPEAT_DAYS days until the date is renewed.

        Works through the brokers in batches and commits as it goes, so a large backlog never hits the
        cron time limit: the scheduler simply runs it again for what is left."""
        today = fields.Date.context_today(self)
        pre_days = self._param_int(PARAM_PRE_DAYS, DEFAULT_PRE_DAYS)
        repeat_days = self._param_int(PARAM_REPEAT_DAYS, DEFAULT_REPEAT_DAYS, minimum=1)
        apps = self.search([('state', '=', 'approved')], order='id')
        if not self._cron_progress(remaining=len(apps)):
            return True                                   # no time left in this run, continue next time
        sent = pending = 0
        for app in apps:
            try:
                with self.env.cr.savepoint():
                    app._sync_expiry_trackers()
                    app._refresh_broker_status()
                    for tracker in app.expiry_tracker_ids:
                        days_left = (tracker.expiry_date - today).days
                        if days_left <= 0:
                            # the expiry date is the first day of expiration: notify, then every N days
                            due = (not tracker.last_alert_date
                                   or (today - tracker.last_alert_date).days >= repeat_days)
                            kind = 'expired'
                        elif days_left <= pre_days:
                            # daily, for the last PRE_DAYS days before expiry
                            due = tracker.pre_alert_date != today
                            kind = 'upcoming'
                        else:
                            continue
                        if due:
                            app._send_expiry_notice(tracker, kind, days_left)
                            tracker.write({'last_alert_date': today} if kind == 'expired'
                                          else {'pre_alert_date': today})
                            sent += 1
            except Exception:
                _logger.exception('Expiry check failed for %s', app.display_name)
            pending += 1
            if pending >= CRON_COMMIT_EVERY:                # committing is costly: do it in chunks
                if not self._cron_progress(pending):
                    _logger.info('Broker expiry check out of time; the scheduler will continue.')
                    pending = 0
                    break
                pending = 0
        if pending:
            self._cron_progress(pending)
        _logger.info('Broker expiry reminders sent: %s', sent)
        return True

    def _send_expiry_notice(self, tracker, kind, days_left):
        self.ensure_one()
        name = self.partner_id.display_name or self.company_name or self.full_name
        if kind == 'upcoming':
            summary = _('%(what)s of %(name)s expires in %(days)s day(s) (%(date)s)',
                        what=tracker.label, name=name, days=days_left, date=tracker.expiry_date)
            xmlid = 'sgc_broker_registration.mail_template_expiry_upcoming'
        else:
            summary = (_('%(what)s of %(name)s EXPIRES TODAY (%(date)s)', what=tracker.label, name=name,
                         date=tracker.expiry_date) if days_left == 0 else
                       _('%(what)s of %(name)s EXPIRED on %(date)s (%(days)s day(s) ago)',
                         what=tracker.label, name=name, date=tracker.expiry_date, days=-days_left))
            xmlid = 'sgc_broker_registration.mail_template_expiry_expired'
        # 1) Odoo notification + to-do for compliance officers (replace the previous open reminder)
        stale = self.activity_ids.filtered(lambda a: a.summary and a.summary.startswith('[%s]' % tracker.label))
        stale.unlink()
        officers = self._officers()
        self.message_post(body=summary, partner_ids=officers.partner_id.ids,
                          subtype_xmlid='mail.mt_note', message_type='notification')
        for user in officers:
            self.activity_schedule('mail.mail_activity_data_todo', user_id=user.id,
                                   date_deadline=tracker.expiry_date,
                                   summary='[%s] %s' % (tracker.label, summary), note=summary)
        # 2) Email to the broker, copying the configured extra recipients
        template = self.env.ref(xmlid, raise_if_not_found=False)
        if template:
            recipients = ([self.email] if self.email else []) + self._extra_notify_emails()
            template.sudo().with_context(
                item_label=tracker.label, item_date=tracker.expiry_date, days_left=abs(days_left)
            ).send_mail(self.id, force_send=False, raise_exception=False,
                        email_values={'email_to': ','.join(recipients)})


class SgcBrokerExpiryTracker(models.Model):
    _name = 'sgc.broker.expiry.tracker'
    _description = 'Broker Expiry Tracker'
    _order = 'expiry_date, id'

    _key_unique = models.Constraint('UNIQUE(application_id, key)', 'One tracker per item.')

    application_id = fields.Many2one('sgc.broker.application', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one(related='application_id.partner_id', store=True)
    key = fields.Char(required=True)
    label = fields.Char(required=True)
    expiry_date = fields.Date(required=True, index=True)
    pre_alert_date = fields.Date(string='Pre-expiry reminder sent', readonly=True)
    last_alert_date = fields.Date(string='Last reminder sent', readonly=True)
    days_left = fields.Integer(compute='_compute_days_left')
    status = fields.Selection([('valid', 'Valid'), ('due', 'Due soon'), ('expired', 'Expired')],
                              compute='_compute_days_left')

    @api.depends('expiry_date')
    def _compute_days_left(self):
        today = fields.Date.context_today(self)
        pre_days = self.env['sgc.broker.application']._param_int(PARAM_PRE_DAYS, DEFAULT_PRE_DAYS)
        for rec in self:
            rec.days_left = (rec.expiry_date - today).days if rec.expiry_date else 0
            rec.status = ('expired' if rec.days_left <= 0 else 'due' if rec.days_left <= pre_days else 'valid')


class SgcBrokerRejectWizard(models.TransientModel):
    _name = 'sgc.broker.reject.wizard'
    _description = 'Reject / request information'

    application_id = fields.Many2one('sgc.broker.application', required=True, ondelete='cascade')
    mode = fields.Selection([('reject', 'Reject'), ('info', 'Request information')], required=True)
    reason = fields.Text(required=True, help='Shown to the applicant in the email.')

    def action_confirm(self):
        self.ensure_one()
        if self.mode == 'reject':
            self.application_id._do_reject(self.reason)
        else:
            self.application_id._do_request_info(self.reason)
        return {'type': 'ir.actions.act_window_close'}
