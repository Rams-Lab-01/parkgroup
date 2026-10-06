# -*- coding: utf-8 -*-
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.image import image_process
from datetime import date, timedelta

_logger = logging.getLogger(__name__)


class PropertyImages(models.Model):
    _name = 'property.images'
    _inherit = ['sgc.critical.audit.mixin']
    _description = 'Property Images (legacy — use property.image for new galleries)'
    _order = 'sequence, id'

    # Entry 52 scope: gallery position and owner. Legacy media -> gate exempt.
    _audit_watched_fields = frozenset({
        'name', 'property_id', 'sequence',
    })
    _audit_unlink_requires_reason = False

    name = fields.Char(string='Title', default='Property Image')
    sequence = fields.Integer(string='Sequence', default=0)
    image = fields.Binary(string='Image', attachment=True)
    property_id = fields.Many2one(
        'property.details',
        string='Property',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        related='property_id.company_id',
        store=True,
        index=True,
    )


class PropertyDetails(models.Model):
    _name = 'property.details'
    _description = 'Property Details'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'sgc.critical.audit.mixin']
    _order = 'name'

    name = fields.Char(string='Property Name', required=True)
    property_code = fields.Char(string='Property Code')
    property_type = fields.Selection([
        ('residential', 'Residential'),
        ('commercial', 'Commercial'),
        ('industrial', 'Industrial'),
        ('land', 'Land'),
    ], string='Property Type', default='residential')
    region_id = fields.Many2one('property.region', string='Region', index=True)
    project_id = fields.Many2one('property.project', string='Project', index=True)
    sub_project_id = fields.Many2one('property.sub.project', string='Sub Project', index=True)
    # Bulk-creation identifiers (filled by the unit-creation wizard; editable
    # afterwards like any other detail).
    floor = fields.Integer(string='Floor')
    unit_number = fields.Char(string='Unit No.', help='e.g. 101, 1204')
    unit_type = fields.Selection([
        ('studio', 'Studio'),
        ('1br', '1 Bedroom'),
        ('2br', '2 Bedrooms'),
        ('3br', '3 Bedrooms'),
        ('4br', '4 Bedrooms'),
        ('penthouse', 'Penthouse'),
    ], string='Unit Type')
    address = fields.Text(string='Address')
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    country_id = fields.Many2one('res.country', string='Country')
    zip = fields.Char(string='ZIP')
    area = fields.Float(string='Area (sq ft)')
    bedrooms = fields.Integer(string='Bedrooms')
    bathrooms = fields.Integer(string='Bathrooms')
    sale_price = fields.Monetary(string='Sale Price', currency_field='currency_id')
    rent_price = fields.Monetary(string='Rent Price', currency_field='currency_id')
    price = fields.Monetary(string='Price', currency_field='currency_id')
    registration_fee = fields.Monetary(
        string='Registration Fee', currency_field='currency_id',
        help="Government registration/transfer fee charged by the emirate's land "
             "registration authority on a property sale (e.g. Dubai Land Department 4%; "
             "Abu Dhabi, Sharjah, Ajman, RAK and the other emirates apply their own rates).")
    registration_fee_percentage = fields.Float(string='Registration Fee %', default=4.0)
    # UAE-standard document identifiers (Makani/DEWA/Title Deed) — used by the
    # Ejari-style rental contract report and the resale purchase agreement.
    # Exposed on the Compliance & Permits tab of the property form (Phase 0.5).
    makani_number = fields.Char(string='Makani Number')
    dewa_premises_number = fields.Char(string='DEWA Premises Number')
    title_deed_number = fields.Char(string='Title Deed Number')
    admin_fee = fields.Monetary(string='Admin Fee', currency_field='currency_id')
    admin_fee_percentage = fields.Float(string='Admin Fee %', default=2.0)
    is_maintenance_service = fields.Boolean(string='Maintenance Service', default=False)
    total_maintenance = fields.Monetary(string='Total Maintenance', currency_field='currency_id')
    is_extra_service = fields.Boolean(string='Extra Service', default=False)
    extra_service_cost = fields.Monetary(string='Extra Service Cost', currency_field='currency_id')
    total_customer_obligation = fields.Monetary(string='Total Customer Obligation', currency_field='currency_id')

    is_payment_plan = fields.Boolean(string='Payment Plan', default=False)
    payment_schedule_id = fields.Many2one('payment.schedule', string='Payment Schedule')
    booking_percentage = fields.Float(string='Booking %', default=10.0)
    booking_type = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed'),
    ], string='Booking Type', default='percentage')
    sold_booking_id = fields.Many2one('property.vendor', string='Sold Booking')
    property_vendor_ids = fields.One2many('property.vendor', 'property_id', string='Bookings/Contracts')
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    owner_id = fields.Many2one('res.partner', string='Owner')
    landlord_id = fields.Many2one('res.partner', string='Landlord')
    listing_agent_id = fields.Many2one('res.partner', string='Listing Agent')
    listing_agent_license_number = fields.Char(string='Agent RERA License No.')
    state = fields.Selection([
        ('available', 'Available'),
        ('booked', 'Booked'),
        ('sold', 'Sold'),
        ('rented', 'Rented'),
        ('maintenance', 'Under Maintenance'),
    ], string='Status', default='available', tracking=True)
    sale_lease = fields.Selection([
        ('sale', 'Sale'),
        ('lease', 'Lease'),
        ('both', 'Both'),
    ], string='Sale/Lease')
    listing_category = fields.Selection([
        ('offplan_sale', 'Off-Plan Sale'),
        ('ready_sale', 'Ready Property Sale'),
        ('resale', 'Resale'),
        ('warehouse', 'Warehouse'),
    ], string='Listing Category')
    active = fields.Boolean(string='Active', default=True)
    is_published_website = fields.Boolean(string='Published on Website', default=False)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)
    description = fields.Html(string='Description')
    amenity_ids = fields.Many2many(
        'property.amenities',
        'property_details_amenity_rel',
        'property_id', 'amenity_id',
        string='Amenities',
    )
    connectivity_ids = fields.Many2many(
        'property.connectivity',
        'property_details_connectivity_rel',
        'property_id', 'connectivity_id',
        string='Nearby Connectivity',
    )
    maintenance_count = fields.Integer(string='Maintenance Requests', compute='_compute_maintenance_count')
    document_count = fields.Integer(string='Documents', compute='_compute_document_count')

    # ------------------------------------------------------------------
    # Pricing & Fees tab -- auto-suggest, not enforced
    # registration_fee/admin_fee/total_customer_obligation stay plain, manually
    # overridable Monetary fields (not compute=/readonly): an operator can
    # still set a genuinely non-standard fee on a specific property. This
    # onchange only auto-fills/refreshes them live while a form is open,
    # so it never touches already-saved values on records nobody re-opens.
    # ------------------------------------------------------------------
    @api.onchange('price', 'registration_fee_percentage', 'admin_fee_percentage',
                   'is_maintenance_service', 'total_maintenance',
                   'is_extra_service', 'extra_service_cost')
    def _onchange_recompute_fees(self):
        for rec in self:
            rec.registration_fee = rec.price * rec.registration_fee_percentage / 100.0
            rec.admin_fee = rec.price * rec.admin_fee_percentage / 100.0
            total = rec.price + rec.registration_fee + rec.admin_fee
            if rec.is_maintenance_service:
                total += rec.total_maintenance
            if rec.is_extra_service:
                total += rec.extra_service_cost
            rec.total_customer_obligation = total

    # ------------------------------------------------------------------
    # Main image (hero / form avatar)
    # ------------------------------------------------------------------
    image_1920 = fields.Binary(string='Image (1920px)', attachment=True)
    image_1024 = fields.Binary(string='Image (1024px)', compute='_compute_property_images', store=True, attachment=True)
    image_512 = fields.Binary(string='Image (512px)', compute='_compute_property_images', store=True, attachment=True)
    image_256 = fields.Binary(string='Image (256px)', compute='_compute_property_images', store=True, attachment=True)

    @api.depends('image_1920')
    def _compute_property_images(self):
        for rec in self:
            if not rec.image_1920:
                rec.image_1024 = rec.image_512 = rec.image_256 = False
                continue
            try:
                rec.image_1024 = image_process(rec.image_1920, size=(1024, 1024))
                rec.image_512 = image_process(rec.image_1920, size=(512, 512))
                rec.image_256 = image_process(rec.image_1920, size=(256, 256))
            except Exception:
                _logger.warning('Could not process image_1920 for property.details id=%s; leaving resized images empty.', rec.id)
                rec.image_1024 = rec.image_512 = rec.image_256 = False

    # ------------------------------------------------------------------
    # RERA / DLD COMPLIANCE FIELDS
    # ------------------------------------------------------------------
    trakheesi_permit_number = fields.Char(
        string="Trakheesi Permit #", size=50,
        help="DLD/RERA Trakheesi permit number required for all property listings")
    permit_issue_date = fields.Date(string="Permit Issue Date")
    permit_expiry_date = fields.Date(
        string="Permit Expiry Date",
        help="Trakheesi permits typically valid for 90 days")
    permit_status = fields.Selection([
        ('valid', 'Valid'),
        ('expired', 'Expired'),
        ('pending', 'Pending'),
        ('revoked', 'Revoked'),
    ], string="Permit Status", default='pending')
    rera_form_a_ref = fields.Many2one(
        'rera.form.a', string="RERA Form A",
        help="Linked Form A listing agreement")
    owner_noc_date = fields.Date(
        string="Owner NOC Date",
        help="Date of No Objection Certificate from owner")
    owner_noc_document = fields.Many2one(
        'property.documents', string="Owner NOC Document")
    trakheesi_qr_code = fields.Binary(
        string="Trakheesi QR Code", attachment=True,
        help="QR code issued alongside the DLD/RERA Trakheesi permit. "
             "Rendered on the website listing, the customer portal and "
             "printed brochures so clients can verify the listing with DLD. "
             "QR codes are mandatory for all property marketing material.")
    portal_ready = fields.Boolean(
        compute='_compute_portal_ready', string="Portal Ready",
        help="All compliance checks passed")
    portal_compliance_errors = fields.Text(
        string="Compliance Errors",
        help="Description of what's blocking portal publishing")
    title_deed_verified = fields.Boolean(
        string="Title Deed Verified",
        help="Title deed has been verified against DLD")
    title_deed_verified_by = fields.Many2one(
        'res.users', string="Verified By")
    title_deed_verified_date = fields.Date(string="Verification Date")

    # ------------------------------------------------------------------
    # Contract smart-button counts
    # ------------------------------------------------------------------
    sale_contract_count = fields.Integer(
        string='Sale Contracts',
        compute='_compute_sale_contract_count',
    )
    rent_contract_count = fields.Integer(
        string='Rent Contracts',
        compute='_compute_rent_contract_count',
    )
    tenancy_details_count = fields.Integer(
        string='Tenancy Details',
        compute='_compute_tenancy_details_count',
    )
    property_vendor_count = fields.Integer(
        string='Vendor/Booking Records',
        compute='_compute_property_vendor_count',
    )

    def _compute_sale_contract_count(self):
        for rec in self:
            rec.sale_contract_count = self.env['sale.contract'].search_count(
                [('property_id', '=', rec.id)])

    def _compute_rent_contract_count(self):
        for rec in self:
            rec.rent_contract_count = self.env['rent.contract'].search_count(
                [('property_id', '=', rec.id)])

    def _compute_tenancy_details_count(self):
        for rec in self:
            rec.tenancy_details_count = self.env['tenancy.details'].search_count(
                [('property_id', '=', rec.id)])

    def _compute_property_vendor_count(self):
        for rec in self:
            rec.property_vendor_count = self.env['property.vendor'].search_count(
                [('property_id', '=', rec.id)])

    def _compute_maintenance_count(self):
        for rec in self:
            rec.maintenance_count = self.env['maintenance.request'].search_count(
                [('property_id', '=', rec.id)])

    def _compute_document_count(self):
        for rec in self:
            rec.document_count = self.env['property.documents'].search_count(
                [('property_id', '=', rec.id)])

    # ------------------------------------------------------------------
    # Trakheesi permit constraints (Phase 0.6)
    # ------------------------------------------------------------------
    # Allow empty values; reject duplicates and malformed values. Format
    # pattern is configurable via ``ir.config_parameter`` key
    # ``sgc_offplan_rental_property_management.trakheesi_permit_format``
    # so the operator (or compliance officer) can update the regex without
    # a code change once DLD/Trakheesi confirms the exact format. The
    # default below is intentionally permissive — see OPEN_QUESTIONS.md.
    @api.constrains('trakheesi_permit_number')
    def _check_trakheesi_permit_number(self):
        import re as _re
        for rec in self:
            value = (rec.trakheesi_permit_number or '').strip()
            if not value:
                # Empty is allowed (compliance gate is at publish time, not save).
                continue
            pattern = rec.env['ir.config_parameter'].sudo().get_param(
                'sgc_offplan_rental_property_management.trakheesi_permit_format',
                default=r'^[A-Za-z0-9._\-]{3,50}$',
            )
            if not _re.match(pattern, value):
                raise ValidationError(_(
                    "Trakheesi Permit Number '%(value)s' does not match the configured format (%(pattern)s). "
                    "Adjust the format in Settings or update the value.",
                    value=value, pattern=pattern,
                ))

    @api.constrains('trakheesi_permit_number')
    def _check_trakheesi_permit_number_unique(self):
        for rec in self:
            value = (rec.trakheesi_permit_number or '').strip()
            if not value:
                continue
            dup = rec.env['property.details'].sudo().with_context(
                active_test=False,
            ).search([
                ('trakheesi_permit_number', '=', value),
                ('id', '!=', rec.id),
            ])
            if dup:
                raise ValidationError(_(
                    "Trakheesi Permit Number '%(value)s' is already used by property %(other)s. "
                    "Permit numbers must be unique per property.",
                    value=value, other=dup[0].display_name or dup[0].name,
                ))

    @api.depends('trakheesi_permit_number', 'permit_expiry_date',
                 'title_deed_number', 'owner_id',
                 'portal_line_ids', 'trakheesi_qr_code')
    def _compute_portal_ready(self):
        for rec in self:
            errors = []
            # Check 1: trakheesi_permit_number is set and not expired
            if not rec.trakheesi_permit_number:
                errors.append("Trakheesi Permit Number is missing")
            elif rec.permit_expiry_date and rec.permit_expiry_date < date.today():
                errors.append("Trakheesi Permit has expired")
                if rec.permit_status != 'revoked':
                    rec.permit_status = 'expired'

            # Check 2: title_deed_number or oqood number is present
            if not rec.title_deed_number:
                errors.append("Title Deed Number is missing")

            # Check 3: At least one valid document of category 'title_deed' or 'oqood'
            has_valid_doc = False
            try:
                for doc in self.env['property.documents'].search([
                    ('property_id', '=', rec.id),
                    '|', ('doc_category', '=', 'title_deed'),
                    ('doc_category', '=', 'oqood'),
                ]):
                    has_valid_doc = True
                    break
            except Exception:
                pass
            if not has_valid_doc:
                errors.append("No valid Title Deed or Oqood document on file")

            # Check 4: owner_id is set
            if not rec.owner_id:
                errors.append("Property Owner is not set")

            # Check 5: portal listings exist
            has_portal_docs = False
            try:
                if rec.portal_line_ids:
                    has_portal_docs = True
            except Exception:
                pass
            if not has_portal_docs:
                errors.append("No portal listings configured")

            # Check 6: Trakheesi QR code uploaded (mandatory for marketing)
            if not rec.trakheesi_qr_code:
                errors.append(
                    "Trakheesi QR Code is missing (required for all property marketing)")

            rec.portal_ready = len(errors) == 0
            rec.portal_compliance_errors = "\n".join(errors) if errors else False

    @api.onchange('trakheesi_permit_number')
    def _onchange_trakheesi_permit_number(self):
        if self.trakheesi_permit_number:
            today = date.today()
            self.permit_issue_date = today
            self.permit_expiry_date = today + timedelta(days=90)
            self.permit_status = 'valid'

    def action_open_rera_form_a(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'RERA Form A',
            'res_model': 'rera.form.a',
            'view_mode': 'form',
            'res_id': self.rera_form_a_ref.id,
            'target': 'current',
        }

    def action_view_sale_contracts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Sale Contracts',
            'res_model': 'sale.contract',
            'view_mode': 'list,form',
            'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id},
        }

    def action_view_rent_contracts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Rent Contracts',
            'res_model': 'rent.contract',
            'view_mode': 'list,form',
            'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id},
        }

    def action_publish(self):
        for rec in self:
            rec.is_published_website = True

    def action_unpublish(self):
        for rec in self:
            rec.is_published_website = False

    def action_archive(self):
        for rec in self:
            rec.active = False

    def action_unarchive(self):
        for rec in self:
            rec.active = True

    def action_view_maintenance(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Maintenance Requests',
            'res_model': 'maintenance.request',
            'view_mode': 'list,form',
            'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id},
        }

    def action_view_documents(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Property Documents',
            'res_model': 'property.documents',
            'view_mode': 'list,form',
            'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id},
        }

    def action_print_brochure(self):
        self.ensure_one()
        return self.env.ref(
            'sgc_offplan_rental_property_management.action_report_property_brochure_luxury'
        ).report_action(self)

    def render_luxury_brochure_pdf(self):
        """Return (pdf_bytes, filename) for the luxury brochure report.

        Single source of truth for every website/controller download path so
        they can't drift onto the older, plain action_report_property_brochure
        report again -- that mismatch (website button live-rendering the non-
        luxury report while the backend Print button used the luxury one) is
        exactly the bug this method replaces call sites for.

        Caches the result into the existing `brochure` binary field (already
        documented as "brochure PDF for lead-gated download") and serves that
        on later calls instead of re-rendering. This isn't just a speed nicety:
        a full-gallery brochure at print resolution takes ~20-30s to render
        (PIL cropping/resizing plus wkhtmltopdf embedding tens of megabytes of
        photos), and visitors were abandoning the download mid-request before
        it finished (nginx logs those as HTTP 499). Caching means only the
        first request for a given property pays that cost. If staff has
        manually uploaded a `brochure` override, that takes precedence and is
        never replaced here -- matches the field's original purpose.
        Note: the cache does not auto-invalidate if photos/details change
        later; clear the Brochure (PDF) field on the property to force a
        fresh render.
        """
        self.ensure_one()
        if self.brochure:
            return base64.b64decode(self.brochure), (self.brochure_filename or 'brochure.pdf')
        report = self.env.ref(
            'sgc_offplan_rental_property_management.action_report_property_brochure_luxury'
        ).sudo()
        pdf_content, _content_type = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
            report, [self.id]
        )
        filename = '%s-brochure.pdf' % (self.name or 'property').replace('/', '-')
        self.sudo().write({
            'brochure': base64.b64encode(pdf_content),
            'brochure_filename': filename,
        })
        return pdf_content, filename

    def action_create_sale_contract(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Sale Contract',
            'res_model': 'sale.contract',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_property_id': self.id,
                'default_seller_id': self.owner_id.id if self.owner_id else False,
                'default_sale_price': self.sale_price or self.price or 0,
                'default_currency_id': self.currency_id.id if self.currency_id else self.company_id.currency_id.id,
                'default_payment_schedule_id': self.payment_schedule_id.id if self.payment_schedule_id else False,
                'default_company_id': self.company_id.id,
            },
        }

    def action_create_rent_contract(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Rent Contract',
            'res_model': 'rent.contract',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_property_id': self.id,
                'default_landlord_id': self.landlord_id.id if self.landlord_id else False,
                'default_rent_amount': self.rent_price or 0,
                'default_currency_id': self.currency_id.id if self.currency_id else self.company_id.currency_id.id,
                'default_payment_schedule_id': self.payment_schedule_id.id if self.payment_schedule_id else False,
                'default_company_id': self.company_id.id,
            },
        }

    def action_create_booking(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Booking / Hold',
            'res_model': 'property.vendor',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_property_id': self.id,
                'default_vendor_id': self.owner_id.id if self.owner_id else False,
                'default_sale_price': self.sale_price or self.price or 0,
                'default_currency_id': self.currency_id.id if self.currency_id else self.company_id.currency_id.id,
                'default_company_id': self.company_id.id,
            },
        }

    # ------------------------------------------------------------------
    # Dashboard API
    # ------------------------------------------------------------------
    @api.model
    def get_property_stats(self):
        """Aggregated KPIs for the Executive Dashboard."""
        company_domain = [('company_id', 'in', self.env.companies.ids)]
        currency_symbol = self.env.company.currency_id.symbol or ''

        # property state breakdown
        state_groups = self.env['property.details'].sudo()._read_group(
            company_domain, groupby=['state'], aggregates=['__count'])
        state_counts = {state: count for state, count in state_groups}

        # property type breakdown
        type_groups = self.env['property.details'].sudo()._read_group(
            company_domain, groupby=['property_type'], aggregates=['__count'])
        type_counts = {property_type: count for property_type, count in type_groups}

        total_property = sum(type_counts.values())
        avail_property = state_counts.get('available', 0)
        sold_property = state_counts.get('sold', 0)
        rented_property = state_counts.get('rented', 0)
        maintenance_property = state_counts.get('maintenance', 0)

        # tenancy contracts
        try:
            contract_groups = self.env['tenancy.details'].sudo()._read_group(
                company_domain, groupby=['contract_type'], aggregates=['__count'])
            contract_counts = {contract_type: count for contract_type, count in contract_groups}
        except Exception:
            contract_counts = {}
        draft_contract = contract_counts.get('new_contract', 0)
        running_contract = contract_counts.get('running_contract', 0)
        expire_contract = contract_counts.get('expire_contract', 0)
        close_contract = contract_counts.get('close_contract', 0)

        # rent bills — rent.bill is the model actually populated by the canonical
        # billing path (rent.contract.action_generate_rent_bills); rent.invoice is
        # never written by that flow, so aggregate rent.bill for the rent KPIs.
        try:
            pending_invoice = self.env['rent.bill'].sudo().search_count(
                [('payment_state', '=', 'not_paid')] + company_domain)
        except Exception:
            pending_invoice = 0
        try:
            rent_groups = self.env['rent.bill'].sudo()._read_group(
                company_domain, aggregates=['amount:sum'])
            full_tenancy_total = (rent_groups[0][0] or 0.0) if rent_groups else 0.0
        except Exception:
            full_tenancy_total = 0.0

        # Booked comes directly from property.details.state, already computed above.
        booked = state_counts.get('booked', 0)

        # sale.contract is the canonical, actively-wired sales pipeline (action_sign/
        # action_complete/action_cancel keep property.details.state in sync with it).
        # property.vendor has no view/actions reachable from the UI and is not used here.
        try:
            sale_groups = self.env['sale.contract'].sudo()._read_group(
                company_domain + [('state', '=', 'completed')],
                aggregates=['sale_price:sum'])
            sold_total = (sale_groups[0][0] or 0.0) if sale_groups else 0.0
        except Exception:
            sold_total = 0.0
        sale_sold = self.env['sale.contract'].sudo().search_count(
            [('state', '=', 'completed')] + company_domain)

        # unpaid sale invoices
        try:
            pending_invoice_sale = self.env['account.move'].sudo().search_count(
                [('sold_id', '!=', False), ('payment_state', '=', 'not_paid')] + company_domain)
        except Exception:
            pending_invoice_sale = 0

        # partners
        try:
            customer_count = self.env['res.partner'].sudo().search_count(
                [('user_type', '=', 'customer')])
            landlord_count = self.env['res.partner'].sudo().search_count(
                [('user_type', '=', 'landlord')])
        except Exception:
            customer_count = 0
            landlord_count = 0

        # geography
        region_count = self.env['property.region'].sudo().search_count([])
        project_count = self.env['property.project'].sudo().search_count(company_domain)
        try:
            subproject_count = self.env['property.sub.project'].sudo().search_count(company_domain)
        except Exception:
            subproject_count = 0

        return {
            'total_property': total_property,
            'avail_property': avail_property,
            'sold_property': sold_property,
            'rented_property': rented_property,
            'maintenance_property': maintenance_property,
            'draft_contract': draft_contract,
            'running_contract': running_contract,
            'expire_contract': expire_contract,
            'close_contract': close_contract,
            'pending_invoice': pending_invoice,
            'pending_invoice_sale': pending_invoice_sale,
            'rent_total': round(full_tenancy_total, 2),
            'sold_total': round(sold_total, 2),
            'booked': booked,
            'sale_sold': sale_sold,
            'customer_count': customer_count,
            'landlord_count': landlord_count,
            'region_count': region_count,
            'project_count': project_count,
            'subproject_count': subproject_count,
            'currency_symbol': currency_symbol,
            'company_name': self.env.company.name or '',
            'property_type': [
                ['Land', 'Residential', 'Commercial', 'Industrial'],
                [type_counts.get('land', 0), type_counts.get('residential', 0),
                 type_counts.get('commercial', 0), type_counts.get('industrial', 0)],
            ],
            'property_state': [
                ['Available', 'Sold', 'Rented', 'Maintenance'],
                [avail_property, sold_property, rented_property, maintenance_property],
            ],
        }

    # ------------------------------------------------------------------
    # Development KPI method (real-data-only dashboard)
    # ------------------------------------------------------------------
    @api.model
    def get_development_kpis(self):
        """Real-data KPIs for the Executive Dashboard, fully drillable."""
        company_domain = [('company_id', 'in', self.env.companies.ids)]
        from datetime import timedelta, date

        # --- Inventory & sales ---
        # Units total / sold / available, per project, for mapping & per-project table
        inv_domain = company_domain
        total_units = self.env['property.details'].sudo().search_count(inv_domain)

        # NOTE: property.details states are 'available' / 'sold' (NOT the
        # sale.contract states). Keeping the two vocabularies separate.
        unit_sold_states = ('sold', 'completed')
        sold_domain = inv_domain + [('state', 'in', unit_sold_states)]
        sold_units = self.env['property.details'].sudo().search_count(sold_domain)
        avail_units = self.env['property.details'].sudo().search_count(inv_domain + [('state', '=', 'available')])

        # Unit mix by type (for the donut). Blank unit_type is reported as "n/a"
        # so the donut never renders an empty slice.
        unit_mix_groups = self.env['property.details'].sudo()._read_group(
            inv_domain, groupby=['unit_type'], aggregates=['__count'])
        unit_mix_labels = [(g[0] or 'n/a').strip() or 'n/a' for g in unit_mix_groups]
        unit_mix_values = [g[1] for g in unit_mix_groups]
        # Stable, meaningful order (biggest first after the known layout)
        _mix_order = {'studio': 0, '1br': 1, '2br': 2, '3br': 3, 'n/a': 9}
        _mix_sorted = sorted(
            zip(unit_mix_labels, unit_mix_values),
            key=lambda kv: (_mix_order.get(kv[0].lower(), 5), -kv[1], kv[0]))
        unit_mix_labels = [kv[0] for kv in _mix_sorted]
        unit_mix_values = [kv[1] for kv in _mix_sorted]
        unit_mix = [unit_mix_labels, unit_mix_values]

        # Sales value (sum of sale_price for sold contracts)
        sale_model = self.env['sale.contract']
        contract_sold_states = ('signed', 'completed')
        sold_contracts = sale_model.sudo().search([('state', 'in', contract_sold_states), ('company_id', 'in', self.env.companies.ids)])
        sold_total = sum(sc.sale_price or 0.0 for sc in sold_contracts)

        # Avg PSF on sold units = total sale price / total area (NOT price per unit).
        # Areas come from the unit record, the contract carries the price.
        sold_rows = self.env['property.details'].sudo().search(sold_domain)
        sold_area_total = sum((pr.area or 0.0) for pr in sold_rows)
        avg_psf_sold = (sold_total / sold_area_total) if sold_area_total else 0.0

        # Units per project (real data)
        projects = self.env['property.project'].sudo().search(company_domain)
        units_by_project = {}
        sold_by_project = {}
        for pr in projects:
            units_by_project[pr.id] = self.env['property.details'].sudo().search_count(
                inv_domain + [('project_id', '=', pr.id)])
            sold_by_project[pr.id] = self.env['property.details'].sudo().search_count(
                sold_domain + [('project_id', '=', pr.id)])

        # --- Collections & receivables ---
        # Collected: sum of paid installments
        installment_model = self.env['sale.contract.installment']
        paid_installments = installment_model.sudo().search([
            ('state', '=', 'paid'), ('contract_id.company_id', 'in', self.env.companies.ids)])
        collected_total = sum(inst.amount or 0.0 for inst in paid_installments)

        # Balance due: all contracts minus collected (including over-collected credits)
        balance_due = 0.0
        for sc in sold_contracts:
            balance_due += (sc.sale_price or 0.0) - (sc.total_paid or 0.0)

        # Collection % = collected_total / sold_total (if sold_total>0)
        collection_pct = (collected_total / sold_total * 100.0) if sold_total else 0.0

        # DSO = balance / sales value * 365 (days)
        dso_days = (balance_due / sold_total * 365.0) if sold_total else 0.0

        # Last activity: most recent payment date across paid installments, else contract date
        last_activity_date = None
        if paid_installments:
            dates = [inst.payment_date for inst in paid_installments if inst.payment_date]
            if dates:
                last_activity_date = max(dates)
        if not last_activity_date:
            contract_dates = [sc.create_date.date() for sc in sold_contracts if sc.create_date]
            if contract_dates:
                last_activity_date = max(contract_dates)

        # Aged > 90 days (balance_due > 0.01), measured from last recorded activity.
        today = fields.Date.context_today(self)
        cutoff = today - timedelta(days=90)
        aged_overdue_units = 0
        aged_overdue_amount = 0.0
        if sold_contracts:
            for sc in sold_contracts:
                if (sc.sale_price or 0.0) - (sc.total_paid or 0.0) > 0.01:
                    la = sc.last_activity_date or sc.contract_date or today
                    if la <= cutoff:
                        aged_overdue_units += 1
                        aged_overdue_amount += (sc.sale_price or 0.0) - (sc.total_paid or 0.0)

        # Real receivables aging buckets, measured in days since the last recorded
        # activity (payment date, else contract date) for contracts that still carry
        # a balance. Buckets are computed from live data - never placeholder zeros.
        aging_buckets = [
            {'label': '0-30 days', 'count': 0, 'amount': 0.0},
            {'label': '31-60 days', 'count': 0, 'amount': 0.0},
            {'label': '61-90 days', 'count': 0, 'amount': 0.0},
            {'label': '91-180 days', 'count': 0, 'amount': 0.0},
            {'label': '> 180 days', 'count': 0, 'amount': 0.0},
        ]
        undated_balance = 0.0
        for sc in sold_contracts:
            bal = (sc.sale_price or 0.0) - (sc.total_paid or 0.0)
            if bal <= 0.01:
                continue
            la = sc.last_activity_date or sc.contract_date
            if not la:
                # No activity date on record: cannot be aged, tracked separately.
                undated_balance += bal
                continue
            age_days = (today - la).days
            if age_days <= 30:
                bucket = 0
            elif age_days <= 60:
                bucket = 1
            elif age_days <= 90:
                bucket = 2
            elif age_days <= 180:
                bucket = 3
            else:
                bucket = 4
            aging_buckets[bucket]['count'] += 1
            aging_buckets[bucket]['amount'] += bal

        # Admin fees
        admin_fees = self.env['property.details'].sudo().search([
            ('admin_fee', '>', 0), ('company_id', 'in', self.env.companies.ids)])
        admin_fees_total = sum(pd.admin_fee for pd in admin_fees)

        # --- Escrow compliance ---
        escrow_model = self.env['escrow.allocation']
        escrow_records = escrow_model.sudo().search(company_domain)
        required_escrow = sum(rec.required_amount for rec in escrow_records if rec.required_amount)
        allocated_escrow = sum(rec.allocated_amount for rec in escrow_records if rec.allocated_amount)
        escrow_shortfall = required_escrow - allocated_escrow
        funded_pct = (allocated_escrow / required_escrow * 100.0) if required_escrow else 0.0

        # Reconciliation: those with source and |variance|<=0.01
        reconciled = [rec for rec in escrow_records if rec.has_source_data and abs(rec.variance_amount or 0.0) <= 0.01]
        recon_units = len(reconciled)
        recon_rate = (recon_units / len(escrow_records) * 100.0) if escrow_records else 0.0

        # Missing source: has_source_data = False
        missing_source = [rec for rec in escrow_records if not rec.has_source_data]
        missing_source_count = len(missing_source)

        # Watchlist counts (real record counts; the UI must never show a hardcoded 0).
        # variance_amount is ALLOCATED - REQUIRED (per the escrow field help text), so a
        # NEGATIVE variance means under-allocated and a POSITIVE one over-allocated.
        # Mirrors the drill-down domains used by the client exactly.
        under_allocated_count = len([rec for rec in escrow_records if (rec.variance_amount or 0.0) < -0.01])
        over_allocated_count = len([rec for rec in escrow_records if (rec.variance_amount or 0.0) > 0.01])
        watchlist_counts = {
            'reconciled': recon_units,
            'under_allocated': under_allocated_count,
            'over_allocated': over_allocated_count,
            'awaiting_source': missing_source_count,
        }

        # --- Per-project totals (for per-project table + dashboard) ---
        # NOTE: relational fields (project_id / property_id) return recordsets, so
        # they must be compared against records or .id - never against a raw int.
        per_project = {}
        for pr in projects:
            pr_recs = pr
            pr_id = pr.id
            sold_val = sum(sc.sale_price or 0.0 for sc in sold_contracts if sc.property_id and sc.property_id.project_id == pr_recs)
            sold_cnt = sold_by_project.get(pr_id, 0)
            collected_val = sum(inst.amount or 0.0 for inst in paid_installments if inst.contract_id and inst.contract_id.property_id and inst.contract_id.property_id.project_id == pr_recs)
            pr_escrow = [rec for rec in escrow_records if rec.project_id == pr_recs]
            required = sum(rec.required_amount for rec in pr_escrow if rec.required_amount)
            allocated = sum(rec.allocated_amount for rec in pr_escrow if rec.allocated_amount)
            variance = required - allocated
            recon = [rec for rec in pr_escrow if rec.has_source_data and abs(rec.variance_amount or 0.0) <= 0.01]
            per_project[pr.code] = {
                'units': units_by_project.get(pr_id, 0),
                'sold': sold_cnt,
                'sell_pct': (sold_cnt / (units_by_project.get(pr_id, 1) or 1) * 100.0),
                'sales_value': sold_val,
                'collected': collected_val,
                'required_escrow': required,
                'allocated_escrow': allocated,
                'variance': variance,
                'recon_rate': (len(recon) / (len(pr_escrow) or 1) * 100.0),
                'funded_pct': (allocated / required * 100.0) if required else 0.0,
            }

        # --- Return map (project code -> coords for map pins) ---
        project_map = {}
        for pr in projects:
            project_map[pr.code] = {
                'name': pr.name or '',
                'city': pr.city or '',
                'lat': pr.geo_latitude or 0.0,
                'lon': pr.geo_longitude or 0.0,
                'units': units_by_project.get(pr.id, 0),
                'count': sold_by_project.get(pr.id, 0),
            }

        return {
            # Company context for the frontend (the web client has no env.company,
            # so the JS reads these instead of crashing on undefined).
            'currency_symbol': (self.env.company.currency_id.symbol or 'AED') if self.env.company else 'AED',
            'company_name': (self.env.company.name or 'Park Group') if self.env.company else 'Park Group',
            # Inventory & sales
            'total_units': total_units,
            'sold_units': sold_units,
            'available_units': avail_units,
            'sell_through_pct': (sold_units / total_units * 100.0) if total_units else 0.0,
            'sales_value': round(sold_total, 2),
            'avg_psf_sold': round(avg_psf_sold, 2),
            'unit_mix': unit_mix,
            'unit_mix_labels': unit_mix_labels,
            'unit_mix_values': unit_mix_values,
            # Collections & receivables
            'collected': round(collected_total, 2),
            'balance_due': round(balance_due, 2),
            'collection_pct': round(collection_pct, 2),
            'dso_days': round(dso_days, 2),
            'aged_overdue_units': aged_overdue_units,
            'aged_overdue_amount': round(aged_overdue_amount, 2),
            'aging_buckets': aging_buckets,
            'undated_balance': round(undated_balance, 2),
            'admin_fees_total': round(admin_fees_total, 2),
            # Escrow compliance
            'required_escrow': round(required_escrow, 2),
            'allocated_escrow': round(allocated_escrow, 2),
            'escrow_shortfall': round(escrow_shortfall, 2),
            'funded_pct': round(funded_pct, 2),
            'recon_rate': round(recon_rate, 2),
            'missing_source_count': missing_source_count,
            'watchlist_counts': watchlist_counts,
            # Per-project data (for per-project table and map)
            'per_project': per_project,
            'project_map': project_map,
            # Drill-down filters
            'company_domain': company_domain,
        }
