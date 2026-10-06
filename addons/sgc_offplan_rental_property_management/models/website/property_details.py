# -*- coding: utf-8 -*-
import base64
import io
import logging

from odoo import models, fields, api, _
from odoo.addons.base.models.ir_http import IrHttp

_logger = logging.getLogger(__name__)
MAX_FLOOR_PLAN_WIDTH = 1600


def _b64(data):
    return base64.b64encode(data).decode('ascii')


class PropertyDetails(models.Model):
    _inherit = 'property.details'

    # Website Images
    image_1920 = fields.Binary(
        string='Image (1920px)',
        attachment=True,
        help='Main property image - 1920px wide recommended'
    )
    image_1024 = fields.Binary(
        string='Image (1024px)',
        compute='_compute_website_images',
        store=True,
        attachment=True,
    )
    image_512 = fields.Binary(
        string='Image (512px)',
        compute='_compute_website_images',
        store=True,
        attachment=True,
    )
    image_256 = fields.Binary(
        string='Image (256px)',
        compute='_compute_website_images',
        store=True,
        attachment=True,
    )

    @api.depends('image_1920')
    def _compute_website_images(self):
        for rec in self:
            rec.image_1024 = rec.image_1920
            rec.image_512 = rec.image_1920
            rec.image_256 = rec.image_1920

    # Website Publishing Fields
    is_published_website = fields.Boolean(
        string='Published on Website',
        default=False,
        help='Check to make this property visible on the public website'
    )
    website_published_date = fields.Datetime(
        string='Website Published Date',
        readonly=True,
        copy=False
    )
    website_views_count = fields.Integer(
        string='Website Views',
        default=0,
        readonly=True,
        help='Number of times this property has been viewed on the website'
    )
    website_inquiry_count = fields.Integer(
        string='Website Inquiries',
        default=0,
        readonly=True,
        help='Number of inquiries received through the website'
    )
    
    # SEO Fields
    website_url = fields.Char(
        string='Website URL',
        compute='_compute_website_url',
        help='Public URL of the property on the website'
    )
    website_meta_title = fields.Char(
        string='Meta Title',
        help='SEO: Page title (50-60 characters recommended)'
    )
    website_meta_description = fields.Text(
        string='Meta Description',
        help='SEO: Page description (150-160 characters recommended)'
    )
    website_meta_keywords = fields.Char(
        string='Meta Keywords',
        help='SEO: Keywords separated by commas'
    )
    
    # Gated Content (lead-gen downloads)
    brochure = fields.Binary(
        string='Brochure (PDF)',
        attachment=True,
        help='Property brochure PDF for lead-gated download'
    )
    brochure_filename = fields.Char(string='Brochure Filename')
    floor_plan = fields.Binary(
        string='Floor Plan (PDF)',
        attachment=True,
        help='Property floor plan PDF for lead-gated download'
    )
    floor_plan_filename = fields.Char(string='Floor Plan Filename')

    # Featured/Premium Status
    website_featured = fields.Boolean(
        string='Featured on Website',
        default=False,
        help='Featured properties appear at the top of listings'
    )
    website_package = fields.Selection([
        ('standard', 'Standard Listing'),
        ('premium', 'Premium Listing'),
        ('featured', 'Featured Listing'),
    ], string='Website Package', default='standard')
    
    website_package_expiry = fields.Date(
        string='Package Expiry Date',
        help='Date when the current package expires'
    )

    @api.depends('name')
    def _compute_website_url(self):
        """Generate SEO-friendly URL for the property"""
        for record in self:
            if record.id:
                record.website_url = f'/properties/{IrHttp._slug(record)}'
            else:
                record.website_url = False

    def action_publish_website(self):
        """Publish property to website"""
        self.ensure_one()
        self.write({
            'is_published_website': True,
            'website_published_date': fields.Datetime.now()
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Published'),
                'message': _('Property has been published to the website'),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_unpublish_website(self):
        """Unpublish property from website"""
        self.ensure_one()
        self.write({'is_published_website': False})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Unpublished'),
                'message': _('Property has been removed from the website'),
                'type': 'warning',
                'sticky': False,
            }
        }

    def action_open_publish_wizard(self):
        """Open wizard for multi-platform publishing"""
        self.ensure_one()
        return {
            'name': _('Publish Property'),
            'type': 'ir.actions.act_window',
            'res_model': 'property.publish.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_property_id': self.id,
            }
        }

    def action_view_website_inquiries(self):
        """Open the gated-form inquiries captured for this property.

        Mirrors action_open_portal_leads (models/portal/property_details_portal.py)
        so both smart buttons behave the same way — this one just points at
        property.website.inquiry (leads from our own site) instead of
        portal.lead (leads from partner portals like Bayut/Dubizzle).
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Website Inquiries'),
            'res_model': 'property.website.inquiry',
            'view_mode': 'list,form',
            'domain': [('property_id', '=', self.id)],
            'context': {'default_property_id': self.id},
            'target': 'current',
        }

    def increment_website_views(self):
        """Increment view counter (called from controller)"""
        self.sudo().write({'website_views_count': self.website_views_count + 1})

    @api.model
    def get_published_properties(self, domain=None, limit=None, order=None):
        """Get published properties for website display"""
        base_domain = [('is_published_website', '=', True)]
        if domain:
            base_domain.extend(domain)
        
        if not order:
            # Featured first, then premium, then by date
            order = 'website_featured desc, website_package desc, website_published_date desc'
        
        return self.search(base_domain, limit=limit, order=order)

    # -------------------------------------------------------------------------
    # Floor plan payload for printable Sale reports
    # -------------------------------------------------------------------------

    def _report_property_payment_plan_lines(self):
        """Payment-plan rows for the property offer sheet (Sale report).

        Projects the payment plan selected on the property ('Pricing & Fees' ->
        'Payment Plan' + schedule) onto the property Sale Price so a prospect
        sees the schedule immediately - no sale.contract is required.
        Returns [] when no plan is configured (report shows the fallback note).
        """
        self.ensure_one()
        schedule = self.payment_schedule_id
        basis = self.sale_price or 0.0
        if not schedule or not basis:
            return []
        anchor = fields.Date.today()
        return schedule._project_report_rows(basis, anchor)

    def _report_floor_plan_data(self):
        """Floor-plan payload for printable Sale reports.

        Returns a dict ready for QWeb:
          {'has': bool, 'kind': 'image'|'pdf'|None, 'name': str|None,
           'source': 'Property floor plan'|'Attached to property'|None,
           'pages': [{'mime', 'b64', 'filename'}],   # normalized embeddable images
           'pdf_b64': str|None}                       # raw PDF for page-append

        The floor plan on the property form wins; otherwise the first matching
        attachment ('*floor*' or '*plan*', excluding brochures). Image payloads
        are normalized (downscaled, alpha-aware) for inline data-URI <img>
        embedding handled by wkhtmltopdf; PDF payloads are appended as pages by
        the ir.actions.report hook rather than embedded.
        """
        self.ensure_one()
        empty = {'has': False, 'kind': None, 'name': None, 'source': None,
                 'pages': [], 'pdf_b64': None}
        raw = None
        name = None
        source = None
        if self.floor_plan:
            raw = self.with_context(bin_size=False).floor_plan
            name = self.floor_plan_filename or 'Floor Plan'
            source = _('Property floor plan')
        if not raw:
            attach = self.env['ir.attachment'].with_context(bin_size=False).search([
                ('res_model', '=', 'property.details'),
                ('res_id', '=', self.id),
                '|',
                ('name', 'ilike', '%floor%'),
                ('name', 'ilike', '%plan%'),
            ], limit=1)
            if attach and not attach.name.lower().lstrip().startswith('brochure'):
                raw = attach.raw
                name = attach.name
                source = _('Attached to property')
        if not raw:
            return empty
        data = self._pm_floor_plan_raw_bytes(raw)
        if not data:
            return empty
        if data[:5] == b'%PDF-':
            return {
                'has': True,
                'kind': 'pdf',
                'name': name,
                'source': source,
                'pages': [],
                'pdf_b64': base64.b64encode(data).decode('ascii'),
            }
        mime = self._pm_mime_for_payload(data, name)
        if mime and mime.startswith('image/'):
            pages = self._pm_normalize_floor_plan_image(data, mime, name or 'Floor Plan')
            if pages:
                return {'has': True, 'kind': 'image', 'name': name,
                        'source': source, 'pages': pages, 'pdf_b64': None}
        return empty

    @api.model
    def _pm_floor_plan_raw_bytes(self, raw):
        """Return the real binary payload of a floor-plan value.

        Attachment-backed Odoo Binary fields may hand back raw bytes, a base64
        string or the base64 text as bytes depending on context - normalize all
        three to actual file bytes so signature detection is reliable.
        """
        def looks(b):
            return (b[:5] == b'%PDF-'
                    or b[:8] == b'\x89PNG\r\n\x1a\n'
                    or b[:3] == b'\xff\xd8\xff'
                    or b[:6] in (b'GIF87a', b'GIF89a')
                    or b[:4] == b'RIFF')

        if isinstance(raw, str):
            try:
                decoded = base64.b64decode(raw, validate=False)
            except Exception:
                decoded = b''
            return decoded if (decoded and looks(decoded)) else b''
        blob = bytes(raw)
        if looks(blob):
            return blob
        head = blob[:8]
        if (head[:6] == b'JVBERi' or head[:8] == b'iVBORw0K'
                or head[:4] in (b'/9j/', b'R0lG', b'UklG')):
            try:
                decoded = base64.b64decode(blob, validate=False)
            except Exception:
                decoded = b''
            if decoded and looks(decoded):
                return decoded
        return b''

    @api.model
    def _pm_mime_for_payload(self, data, filename=None):
        """Guess media type from the payload signature, falling back to the name."""
        if data[:8] == b'\x89PNG\r\n\x1a\n':
            return 'image/png'
        if data[:3] == b'\xff\xd8\xff':
            return 'image/jpeg'
        if data[:6] in (b'GIF87a', b'GIF89a'):
            return 'image/gif'
        if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
            return 'image/webp'
        try:
            import mimetypes
            return mimetypes.guess_type(filename or '')[0]
        except Exception:
            return None

    @api.model
    def _pm_normalize_floor_plan_image(self, data, mime, filename):
        """Return a small embeddable ['mime', 'b64', 'filename'] rendering.

        Downscales wide images and converts alpha/webp payloads to PNG so the
        resulting data URI (and the wkhtmltopdf-rendered PDF) stays small and
        universally decodable. Falls back to the raw bytes when PIL is missing.
        """
        try:
            from PIL import Image, ImageOps
            image = Image.open(io.BytesIO(data))
            image.load()
            try:
                image = ImageOps.exif_transpose(image)
            except Exception:
                pass
            if image.width > MAX_FLOOR_PLAN_WIDTH:
                height = int(image.height * MAX_FLOOR_PLAN_WIDTH / image.width)
                image = image.resize((MAX_FLOOR_PLAN_WIDTH, height), Image.Resampling.LANCZOS)
            if image.mode in ('RGBA', 'LA', 'P', 'PA'):
                output = image.convert('RGBA')
                out_mime = 'image/png'
            else:
                output = image.convert('RGB')
                out_mime = 'image/jpeg'
            buffer = io.BytesIO()
            output.save(buffer, format='PNG' if out_mime == 'image/png' else 'JPEG', optimize=True)
            return [{'mime': out_mime, 'b64': _b64(buffer.getvalue()), 'filename': filename}]
        except Exception:
            _logger.warning("Falling back to raw floor-plan bytes for %s", filename)
            return [{'mime': mime, 'b64': _b64(data), 'filename': filename}]
