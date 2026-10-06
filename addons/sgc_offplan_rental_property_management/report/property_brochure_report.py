# -*- coding: utf-8 -*-
import base64
import io
import logging
import os
import tempfile

from werkzeug.urls import url_quote_plus as quote_plus

from odoo import api, models
from odoo.tools.image import image_data_uri

_logger = logging.getLogger(__name__)


class PropertyBrochureReport(models.AbstractModel):
    """Report values for the property brochure PDF.

    Image fields on these models are `fields.Image`, which Odoo may store as
    WebP. wkhtmltopdf's bundled rendering engine cannot decode WebP at all,
    so every image embedded in the brochure must be converted to JPEG first.

    That conversion can't go through `odoo.tools.image.image_process()`
    directly: that helper opens the source via `PIL.Image.open(io.BytesIO(...))`,
    and within the full Odoo runtime PIL's WebP plugin fails to identify a
    WebP image from a BytesIO stream (confirmed by direct reproduction) even
    though it opens the identical bytes fine from a real file path. The
    conversion below works around this by writing the source to a temp file
    before opening it with PIL, then re-encoding as JPEG in memory.
    """
    _name = 'report.sgc_offplan_rental_property_management.report_property_brochure'
    _description = 'Property Brochure Report'
    # AbstractModel never creates a table, but Odoo still validates the
    # auto-derived table name length for every model; the dotted _name
    # above (required so Odoo's report dispatch can find this class by
    # report_name) is too long once the module name is folded in, so give
    # it an explicit short one instead.
    _table = 'sgc_offplan_report_property_brochure'

    @staticmethod
    def _guess_suffix(raw):
        if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
            return '.webp'
        if raw[:3] == b'\xff\xd8\xff':
            return '.jpg'
        if raw[:8] == b'\x89PNG\r\n\x1a\n':
            return '.png'
        if raw[:6] in (b'GIF87a', b'GIF89a'):
            return '.gif'
        return '.img'

    @api.model
    def _convert_to_jpeg_b64(self, b64_source):
        # Always returns bytes (possibly empty), never a str/False/None:
        # the value flows straight into image_data_uri(), which calls
        # .decode() on it unconditionally and crashes on a plain str.
        if not b64_source:
            return b''
        from PIL import Image

        raw = base64.b64decode(b64_source)
        fd, tmp_path = tempfile.mkstemp(suffix=self._guess_suffix(raw))
        try:
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(raw)
            image = Image.open(tmp_path)
            if image.format == 'JPEG':
                return b64_source
            image = image.convert('RGB')
            buf = io.BytesIO()
            image.save(buf, format='JPEG', quality=90)
            return base64.b64encode(buf.getvalue())
        except Exception:
            _logger.warning('Could not convert image to JPEG for brochure report; skipping image.', exc_info=True)
            return b''
        finally:
            os.unlink(tmp_path)

    @api.model
    def _trakheesi_qr_uri(self, b64_source):
        """Lossless data URI for the uploaded Trakheesi QR code.

        Deliberately not routed through _convert_to_jpeg_b64(): re-encoding a
        hard black/white QR as JPEG softens exactly the module edges a scanner
        depends on. image_data_uri() wants the base64 source as bytes -- it
        sniffs the mimetype from the first base64 character and calls
        .decode() on the argument -- and Odoo 19's Binary field already hands
        templates base64 as bytes (odoo/orm/fields_binary.py), so bytes pass
        straight through; a str is encoded defensively.
        PNG/JPEG/GIF/SVG uploads all render with the right mimetype.
        """
        if not b64_source:
            return ''
        if isinstance(b64_source, str):
            # Pre-19 call sites / contexts hand over the base64 str directly.
            b64_source = b64_source.encode()
        return image_data_uri(b64_source)

    @api.model
    def _qr_url_for(self, prop):
        """Absolute, real URL encoded into the brochure QR code.

        Same contract as the luxury brochure: a scan must land on a live
        page for this property (public unit page when published, else the
        project page, else the site root).  No token is fabricated - the
        model carries no access_token field today; if one is ever added
        the value is appended automatically.
        """
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        if prop.is_published_website:
            url = '%s/offplan/property/%s' % (base, prop.id)
        elif prop.project_id:
            url = '%s/offplan/project/%s' % (base, prop.project_id.id)
        else:
            url = base
        token = getattr(prop, 'access_token', False)
        if token:
            url = '%s?access_token=%s' % (url, token)
        return url

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['property.details'].browse(docids)
        return {
            'doc_ids': docids,
            'doc_model': 'property.details',
            'docs': docs,
            'convert_image': self._convert_to_jpeg_b64,
            'trakheesi_qr_uri': self._trakheesi_qr_uri,
            'quote_plus': quote_plus,
            'qr_url_for': self._qr_url_for,
        }
