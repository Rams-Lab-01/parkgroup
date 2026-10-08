import base64
import logging
import mimetypes
from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import _, fields, http
from odoo.exceptions import UserError, ValidationError
from odoo.http import request
from odoo.tools.translate import LazyTranslate

from ..models.broker_application import (
    EDITABLE_STATES, MAX_APPLICATIONS_PER_EMAIL_PER_DAY, normalize_email)
from ..models.document_type import EMIRATES

_logger = logging.getLogger(__name__)
_lt = LazyTranslate(__name__)

REGISTER_FIELDS = ['email']
DETAIL_FIELDS = ['applicant_type', 'emirate', 'company_name', 'full_name', 'phone', 'street', 'city', 'po_box', 'website',
                 'nationality_id',
                 'trade_license_no', 'trade_license_authority', 'orn', 'brn', 'vat_trn', 'goaml_id',
                 'emirates_id', 'passport_no', 'signatory_name', 'signatory_title',
                 'bank_name', 'iban', 'account_holder']
DATE_FIELDS = ['trade_license_issue_date', 'trade_license_expiry', 'regulator_expiry']
PARAM_MAX_PER_IP = 'sgc_broker.max_registrations_per_ip_hour'
PARAM_OPEN_SIGNUP = 'sgc_broker.open_signup'
RESUME_COOLDOWN_MINUTES = 5

CODE_MESSAGES = {
    'bad': _lt('That code is not correct. Please try again.'),
    'expired': _lt('The code has expired. Request a new one.'),
    'locked': _lt('Too many wrong attempts. Request a new code.'),
    'none': _lt('Request a verification code first.'),
}
SEND_MESSAGES = {
    'cooldown': _lt('Please wait %s seconds before requesting another code.'),
    'limit': _lt('Too many codes requested. Try again in an hour.'),
}


def _clean(post, keys):
    return {k: (post.get(k) or '').strip() for k in keys if post.get(k) is not None}


def _error_text(exc):
    return exc.args[0] if exc.args else str(exc)


class BrokerRegistration(http.Controller):

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _app(self, token):
        if not token:
            return request.env['sgc.broker.application']
        return request.env['sgc.broker.application'].sudo().search(
            [('access_token', '=', token)], limit=1)

    def _ip(self):
        return request.httprequest.remote_addr or ''

    def _register_values(self, values=None, error=None):
        return {
            'values': values or {},
            'error': error,
        }

    def _application_values(self, app, error=None, info=None, **extra):
        applicable = app._applicable_types()
        by_type = {}
        for doc in app.document_ids:
            by_type.setdefault(doc.type_id.id, request.env['sgc.broker.application.document'])
            by_type[doc.type_id.id] |= doc
        vals = {
            'app': app, 'types': applicable, 'docs_by_type': by_type,
            'can_edit': app.state in EDITABLE_STATES, 'error': error, 'info': info,
            'emirates': dict(EMIRATES), 'today': fields.Date.context_today(app),
            'countries': request.env['res.country'].sudo().search([]),
            'max_mb': request.env['sgc.broker.application.document'].sudo()._max_bytes() // (1024 * 1024),
        }
        vals.update(extra)
        return vals

    def _redirect_for(self, app):
        token = app.access_token
        if not app.email_verified:
            return request.redirect('/broker/verify/%s' % token)
        return request.redirect('/broker/application/%s' % token)

    # ------------------------------------------------------------------
    # 1. Registration form
    # ------------------------------------------------------------------
    def _signup_open(self):
        value = request.env['ir.config_parameter'].sudo().get_param(PARAM_OPEN_SIGNUP)
        return value in (False, None, '', 'True', 'true', '1')   # unset = open

    @http.route('/brokers', type='http', auth='public', website=True, sitemap=True)
    def landing(self, **kw):
        types = request.env['sgc.broker.document.type'].sudo().search([('active', '=', True)])
        return request.render('sgc_broker_registration.landing_page', {
            'signup_open': self._signup_open(),
            'individual_docs': types.filtered(lambda t: t.applicant_type in ('both', 'individual')),
            'company_docs': types.filtered(lambda t: t.applicant_type in ('both', 'company')),
            'emirates': EMIRATES,
        })

    @http.route('/broker/resume', type='http', auth='public', website=True, methods=['GET', 'POST'],
                sitemap=False)
    def resume(self, email='', **kw):
        """Applicants who lost their link: the link is only ever mailed to the address on the application, and
        the answer is identical whether or not an application exists (no account enumeration)."""
        if request.httprequest.method != 'POST':
            return request.render('sgc_broker_registration.resume_page', {'sent': False})
        try:
            address = normalize_email((email or '').strip())
        except Exception:
            address = ''
        if address:
            app = request.env['sgc.broker.application'].sudo().search(
                [('email', '=', address), ('state', '!=', 'rejected')], limit=1)
            now = fields.Datetime.now()
            if app and (not app.resume_last_sent
                        or app.resume_last_sent < now - timedelta(minutes=RESUME_COOLDOWN_MINUTES)):
                app.resume_last_sent = now
                if app.state == 'draft':
                    app.action_send_code()
                elif app.state != 'approved':
                    app.env.ref('sgc_broker_registration.mail_template_resume_link').sudo().send_mail(
                        app.id, force_send=True, raise_exception=False)
        return request.render('sgc_broker_registration.resume_page', {'sent': True})

    @http.route('/broker/register', type='http', auth='public', website=True, sitemap=True)
    def register_form(self, **kw):
        if not self._signup_open():
            return request.render('sgc_broker_registration.closed_page', {})
        return request.render('sgc_broker_registration.register_page', self._register_values())

    @http.route('/broker/register/submit', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False)
    def register_submit(self, **post):
        if not self._signup_open():
            return request.render('sgc_broker_registration.closed_page', {})
        values = _clean(post, REGISTER_FIELDS)
        if post.get('website_hp'):        # honeypot: bots fill hidden fields
            return request.redirect('/broker/register')
        Application = request.env['sgc.broker.application'].sudo()
        try:
            if not values.get('email'):
                raise ValidationError(_('Email is required.'))
            values['email'] = normalize_email(values['email'])

            now = fields.Datetime.now()
            if Application.search_count([('create_ip', '=', self._ip()),
                                         ('create_date', '>', now - timedelta(hours=1))]) \
                    >= Application._param_int(PARAM_MAX_PER_IP, 10, minimum=1):
                raise ValidationError(_('Too many registrations from your network. Try again later.'))

            existing = Application.search([('email', '=', values['email']), ('state', '!=', 'rejected')],
                                          limit=1)
            if existing:
                # Never hand the existing token to a stranger: mail it to the owner of the address.
                if existing.state == 'draft':
                    existing.action_send_code()
                elif existing.state != 'approved':
                    existing.env.ref('sgc_broker_registration.mail_template_resume_link').sudo().send_mail(
                        existing.id, force_send=True, raise_exception=False)
                return request.render('sgc_broker_registration.already_registered_page', {})
            if Application.search_count([('email', '=', values['email']),
                                         ('create_date', '>', now - timedelta(days=1))]) \
                    >= MAX_APPLICATIONS_PER_EMAIL_PER_DAY:
                raise ValidationError(_('Too many attempts for this email today.'))

            values.update({'create_ip': self._ip(), 'company_id': request.website.company_id.id})
            try:
                with request.env.cr.savepoint():
                    app = Application.create(values)
            except IntegrityError:
                # lost a race with another request for the same email: behave like the duplicate case
                existing = Application.search([('email', '=', values['email']), ('state', '!=', 'rejected')], limit=1)
                if existing and existing.state != 'approved':
                    existing.env.ref('sgc_broker_registration.mail_template_resume_link').sudo().send_mail(
                        existing.id, force_send=True, raise_exception=False)
                return request.render('sgc_broker_registration.already_registered_page', {})
        except (ValidationError, UserError) as exc:
            return request.render('sgc_broker_registration.register_page',
                                  self._register_values(values=post, error=_error_text(exc)))
        app.action_send_code()
        return request.redirect('/broker/verify/%s' % app.access_token)

    # ------------------------------------------------------------------
    # 2. Email verification
    # ------------------------------------------------------------------
    @http.route('/broker/verify/<string:token>', type='http', auth='public', website=True, sitemap=False)
    def verify_form(self, token, **kw):
        app = self._app(token)
        if not app:
            return request.not_found()
        if app.email_verified:
            return request.redirect('/broker/application/%s' % token)
        return request.render('sgc_broker_registration.verify_page', {'app': app, 'error': None, 'info': None})

    @http.route('/broker/verify/<string:token>/check', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False)
    def verify_check(self, token, code='', **kw):
        app = self._app(token)
        if not app:
            return request.not_found()
        result = app.verify_code(code)
        if result == 'ok':
            return request.redirect('/broker/application/%s' % token)
        return request.render('sgc_broker_registration.verify_page',
                              {'app': app, 'error': str(CODE_MESSAGES.get(result)), 'info': None})

    @http.route('/broker/verify/<string:token>/resend', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False)
    def verify_resend(self, token, **kw):
        app = self._app(token)
        if not app:
            return request.not_found()
        status, wait = app.action_send_code()
        if status == 'verified':
            return request.redirect('/broker/application/%s' % token)
        error = info = None
        if status == 'ok':
            info = _('A new code has been sent to %s.', app.email)
        else:
            error = (str(SEND_MESSAGES[status]) % wait) if status == 'cooldown' else str(SEND_MESSAGES[status])
        return request.render('sgc_broker_registration.verify_page', {'app': app, 'error': error, 'info': info})

    # ------------------------------------------------------------------
    # 3. Application: details, documents, submit
    # ------------------------------------------------------------------
    @http.route('/broker/application/<string:token>', type='http', auth='public', website=True, sitemap=False)
    def application_page(self, token, **kw):
        app = self._app(token)
        if not app:
            return request.not_found()
        if not app.email_verified:
            return self._redirect_for(app)
        return request.render('sgc_broker_registration.application_page', self._application_values(app))

    def _editable_app(self, token):
        app = self._app(token)
        if not app or not app.email_verified:
            return None
        return app

    @http.route('/broker/application/<string:token>/details', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False)
    def application_details(self, token, **post):
        app = self._editable_app(token)
        if not app:
            return request.not_found()
        if app.state not in EDITABLE_STATES:
            return request.render('sgc_broker_registration.application_page',
                                  self._application_values(app, error=_('This application can no longer be changed.')))
        try:
            vals = _clean(post, DETAIL_FIELDS)
            for key in DATE_FIELDS:
                if post.get(key):
                    try:
                        vals[key] = fields.Date.to_date(post[key])
                    except Exception:
                        raise ValidationError(_('Invalid date for %s.', app._fields[key].string))
                else:
                    vals[key] = False
            if post.get('applicant_type') and post['applicant_type'] not in ('individual', 'company'):
                raise ValidationError(_('Choose the applicant type.'))
            if post.get('emirate') and post['emirate'] not in dict(EMIRATES):
                raise ValidationError(_('Choose the emirate / regulator.'))
            if post.get('nationality_id'):
                nat = post['nationality_id']
                if nat.isdigit() and request.env['res.country'].sudo().browse(int(nat)).exists():
                    vals['nationality_id'] = int(nat)
                else:
                    vals['nationality_id'] = False
            else:
                vals['nationality_id'] = False
            vals = request.env['sgc.broker.application'].sudo()._clean_vals(vals)
            for empty_key in [k for k, v in vals.items() if v == '']:
                vals[empty_key] = False
            app.write(vals)
            app.message_post(body=_('Application details updated.'))
        except (ValidationError, UserError) as exc:
            return request.render('sgc_broker_registration.application_page',
                                  self._application_values(app, error=_error_text(exc)))
        return request.render('sgc_broker_registration.application_page',
                              self._application_values(app, info=_('Details saved.')))

    @http.route('/broker/application/<string:token>/upload', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False)
    def application_upload(self, token, type_id=None, file=None, issue_date=None, expiry_date=None, **kw):
        app = self._editable_app(token)
        if not app:
            return request.not_found()
        try:
            if app.state not in EDITABLE_STATES:
                raise ValidationError(_('This application can no longer be changed.'))
            dtype = request.env['sgc.broker.document.type'].sudo().browse(int(type_id or 0)).exists()
            if not dtype or dtype not in app._applicable_types():
                raise ValidationError(_('Unknown document type.'))
            if file is None or not getattr(file, 'filename', ''):
                raise ValidationError(_('Choose a file to upload.'))
            max_bytes = request.env['sgc.broker.application.document'].sudo()._max_bytes()
            raw = file.read(max_bytes + 1)
            if not raw:
                raise ValidationError(_('The uploaded file is empty.'))
            vals = {'application_id': app.id, 'type_id': dtype.id, 'filename': file.filename[:200],
                    'file': base64.b64encode(raw)}
            for key, value in (('issue_date', issue_date), ('expiry_date', expiry_date)):
                if value:
                    try:
                        vals[key] = fields.Date.to_date(value)
                    except Exception:
                        raise ValidationError(_('Invalid date.'))
            today = fields.Date.context_today(app)
            if dtype.has_expiry:
                if not vals.get('expiry_date'):
                    raise ValidationError(_('Enter the expiry date for "%s".', dtype.name))
                if vals['expiry_date'] <= today:
                    raise ValidationError(_('"%s" has expired. Upload a valid document.', dtype.name))
            request.env['sgc.broker.application.document'].sudo().create(vals)
            app.message_post(body=_('Document uploaded: %s (%s).', dtype.name, vals['filename']))
        except (ValidationError, UserError, ValueError) as exc:
            return request.render('sgc_broker_registration.application_page',
                                  self._application_values(app, error=_error_text(exc)))
        return request.render('sgc_broker_registration.application_page',
                              self._application_values(app, info=_('Document uploaded.')))

    @http.route('/broker/application/<string:token>/delete/<int:doc_id>', type='http', auth='public',
                website=True, methods=['POST'], sitemap=False)
    def application_delete_doc(self, token, doc_id, **kw):
        app = self._editable_app(token)
        if not app:
            return request.not_found()
        doc = app.document_ids.filtered(lambda d: d.id == doc_id)
        error = None
        if app.state not in EDITABLE_STATES or doc.state == 'accepted':
            error = _('This document can no longer be removed.')
        elif not doc:
            error = _('Document not found.')
        else:
            filename = doc.filename
            doc.sudo().unlink()
            app.message_post(body=_('Document removed: %s.', filename))
        return request.render('sgc_broker_registration.application_page',
                              self._application_values(app, error=error))

    @http.route('/broker/application/<string:token>/review', type='http', auth='public', website=True,
                sitemap=False)
    def application_review(self, token, **kw):
        app = self._editable_app(token)
        if not app:
            return request.not_found()
        if app.state not in EDITABLE_STATES:
            return request.render('sgc_broker_registration.application_page',
                                  self._application_values(app, error=_('This application can no longer be changed.')))
        missing_details = app._missing_details()
        if app.missing_type_ids or missing_details:
            parts = []
            if missing_details:
                parts.append(_('Missing details: %s', ', '.join(missing_details)))
            if app.missing_type_ids:
                parts.append(_('Missing documents: %s', ', '.join(app.missing_type_ids.mapped('name'))))
            return request.render('sgc_broker_registration.application_page',
                                  self._application_values(app, error=_('Complete all required information and documents before reviewing. %s', ' '.join(parts))))
        app.write({'review_opened_at': fields.Datetime.now()})
        app.message_post(body=_('Review page opened by the applicant.'))
        return request.render('sgc_broker_registration.review_page', self._application_values(app))

    @http.route('/broker/application/<string:token>/submit', type='http', auth='public', website=True,
                methods=['POST'], sitemap=False)
    def application_submit(self, token, **post):
        app = self._editable_app(token)
        if not app:
            return request.not_found()
        if app.state not in EDITABLE_STATES:
            return request.render('sgc_broker_registration.review_page',
                                  self._application_values(app, error=_('This application can no longer be changed.')))
        try:
            declared = request.env['sgc.broker.application'].sudo()._clean_vals(
                {'declared_name': post.get('declared_name') or ''})
            app.write({
                'accept_terms': bool(post.get('accept_terms')),
                'accept_aml': bool(post.get('accept_aml')),
                'accept_accuracy': bool(post.get('accept_accuracy')),
                'declared_name': declared['declared_name'],
            })
            app.action_submit(ip=self._ip())
        except (ValidationError, UserError) as exc:
            return request.render('sgc_broker_registration.review_page',
                                  self._application_values(app, error=_error_text(exc)))
        return request.redirect('/broker/application/%s/thanks' % app.access_token)

    @http.route('/broker/application/<string:token>/thanks', type='http', auth='public', website=True,
                sitemap=False)
    def application_thanks(self, token, **kw):
        app = self._app(token)
        if not app:
            return request.not_found()
        if not app.email_verified or app.state not in ('submitted', 'in_review', 'needs_info', 'approved', 'rejected'):
            return self._redirect_for(app)
        return request.render('sgc_broker_registration.thanks_page', {'app': app})

    @http.route('/broker/application/<string:token>/document/<int:doc_id>', type='http', auth='public',
                website=True, sitemap=False)
    def application_document(self, token, doc_id, **kw):
        """Let the applicant download a file they uploaded (e.g. the signed agreement)."""
        app = self._editable_app(token)
        doc = app and app.document_ids.filtered(lambda d: d.id == doc_id)
        if not doc:
            return request.not_found()
        mime = mimetypes.guess_type(doc.filename)[0] or 'application/octet-stream'
        return request.make_response(base64.b64decode(doc.file), headers=[
            ('Content-Type', mime), ('X-Content-Type-Options', 'nosniff'),
            ('Content-Disposition', http.content_disposition(doc.filename))])

    @http.route('/broker/application/<string:token>/agreement', type='http', auth='public', website=True,
                sitemap=False)
    def application_agreement(self, token, **kw):
        app = self._editable_app(token)
        if not app:
            return request.not_found()
        report = request.env.ref('sgc_broker_registration.action_report_broker_agreement').sudo()
        try:
            content, _fmt = report._render_qweb_pdf(report.report_name, [app.id])
            mime, ext = 'application/pdf', 'pdf'
        except Exception:
            _logger.warning('PDF engine unavailable, serving the agreement as HTML', exc_info=True)
            content, _fmt = report._render_qweb_html(report.report_name, [app.id])
            mime, ext = 'text/html', 'html'
        filename = 'Brokerage-Agreement-%s.%s' % (app.name.replace('/', '-'), ext)
        return request.make_response(content, headers=[
            ('Content-Type', mime), ('Content-Disposition', http.content_disposition(filename))])


class BrokerCommissionPortal(http.Controller):

    @http.route('/my/commissions', type='http', auth='user', website=True, sitemap=False)
    def my_commissions(self, **kw):
        """Commission lines of the logged-in broker: deal progress and payout status.

        Omits the buyer and the sale price: a broker sees their own commission and
        where the deal stands, not the customer's details. Needs the offplan module.
        """
        Line = request.env.get('property.commission.line')
        if Line is None:
            return request.not_found()
        partner = request.env.user.partner_id.commercial_partner_id
        lines = Line.sudo().search([('partner_id', 'child_of', partner.id), ('state', '!=', 'cancelled')],
                                   order='id desc')
        Contract = request.env['sale.contract']
        return request.render('sgc_broker_registration.portal_my_commissions_page', {
            'lines': lines,
            'total_commission': sum(lines.mapped('amount_total')),
            'total_paid': sum(lines.filtered(lambda l: l.payment_state == 'paid').mapped('amount_total')),
            'labels': {
                'deal': dict(Contract._fields['state'].selection),
                'sale_payment': dict(Contract._fields['overall_payment_state'].selection),
                'line': dict(Line._fields['state'].selection),
                'payout': dict(Line._fields['payment_state'].selection),
            },
            'page_name': 'my_commissions',
        })
