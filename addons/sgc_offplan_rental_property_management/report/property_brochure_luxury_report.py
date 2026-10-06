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


class PropertyBrochureLuxuryReport(models.AbstractModel):
    """Report values for the luxury property brochure PDF.

    Full-bleed A4 luxury design with deep navy/gold aesthetic.
    All images go through WebP-to-JPEG conversion identical to the
    standard brochure report to ensure wkhtmltopdf compatibility.
    """
    _name = "report.sgc_offplan_rental_property_management.report_property_brochure_luxury"
    _description = "Property Brochure Luxury Report"
    _table = "sgc_offplan_report_brochure_luxury"

    @staticmethod
    def _guess_suffix(raw):
        if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            return ".webp"
        if raw[:3] == b"\xff\xd8\xff":
            return ".jpg"
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            return ".png"
        if raw[:6] in (b"GIF87a", b"GIF89a"):
            return ".gif"
        return ".img"

    @api.model
    def _convert_to_jpeg_b64(self, b64_source):
        # Always returns bytes (possibly empty), never a str/False/None:
        # the value flows straight into image_data_uri(), which calls
        # .decode() on it unconditionally and crashes on a plain str.
        if not b64_source:
            return b''
        from PIL import Image

        raw = base64.b64decode(b64_source)
        # Written to a real file and reopened by path, not Image.open(BytesIO(raw)):
        # extended-format WebP (VP8X container -- ICC profile/alpha/EXIF present,
        # common on real property photos) fails with PIL.UnidentifiedImageError
        # when read from an in-memory stream on this server's Pillow/libwebp
        # build, even though the identical bytes decode fine from a path. Cost
        # a real brochure its cover photo (silently fell back to a blank navy
        # rectangle) before this was caught -- see debug session notes for the
        # repro. The disk round-trip is not the render-time bottleneck anyway
        # (measured ~3.7s for all image processing combined vs wkhtmltopdf's
        # own ~9-12s), so there's no performance reason to avoid it here.
        fd, tmp_path = tempfile.mkstemp(suffix=self._guess_suffix(raw))
        try:
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(raw)
            image = Image.open(tmp_path)
            if image.format == 'JPEG':
                return b64_source
            image = image.convert('RGB')
            buf = io.BytesIO()
            image.save(buf, format='JPEG', quality=92)
            return base64.b64encode(buf.getvalue())
        except Exception:
            _logger.warning(
                "Could not convert image to JPEG for luxury brochure; skipping.",
                exc_info=True,
            )
            return b''
        finally:
            os.unlink(tmp_path)

    @api.model
    def _render_crop_fit(self, b64_source, target_w, target_h, quality=90):
        """Return a JPEG data URI center-cropped to exactly target_w:target_h.

        Why this exists: wkhtmltopdf's QtWebKit engine does not honor CSS
        object-fit, so any <img> forced into a box via width:100%;
        height:100% on a mismatched aspect ratio gets stretched, not
        cropped -- this is what produced the visibly squashed banner/thumb
        photos on the interior page. Doing the "cover" crop with PIL before
        the image ever reaches the template sidesteps the limitation
        entirely: once the JPEG's own aspect ratio already matches the CSS
        box, a plain width:100%/height:100% is a lossless 1:1 fit, not a
        stretch.

        target_w/target_h should be the box's real physical print size in
        pixels at the print DPI we want (300dpi), not CSS/screen pixels --
        the resulting JPEG is embedded as-is, so its own pixel count is what
        determines print sharpness regardless of wkhtmltopdf's render dpi.
        We never upscale past what the source can honestly deliver: if the
        cropped source is smaller than the requested target, we keep the
        source's native resolution instead of fabricating detail with
        Lanczos upsampling.
        """
        from PIL import Image
        if not b64_source:
            return None
        try:
            raw = base64.b64decode(b64_source)
            # See _convert_to_jpeg_b64 for why this goes through a real file
            # path rather than Image.open(BytesIO(raw)) -- extended-format
            # WebP fails to decode from an in-memory stream here.
            fd, tmp_path = tempfile.mkstemp(suffix=self._guess_suffix(raw))
            try:
                with os.fdopen(fd, "wb") as tmp:
                    tmp.write(raw)
                src = Image.open(tmp_path).convert("RGB")
            finally:
                os.unlink(tmp_path)
        except Exception:
            _logger.warning(
                "Image open failed for crop-fit render; skipping.",
                exc_info=True,
            )
            return None

        src_w, src_h = src.size
        # Center-crop into the target aspect ratio without stretching.
        target_ratio = target_w / target_h
        src_ratio = src_w / src_h if src_h else target_ratio
        if src_ratio > target_ratio:
            # Source is wider than target -- crop horizontally.
            new_w = max(1, int(src_h * target_ratio))
            offset = (src_w - new_w) // 2
            src = src.crop((offset, 0, offset + new_w, src_h))
        else:
            # Source is taller than target -- crop vertically.
            new_h = max(1, int(src_w / target_ratio))
            offset = (src_h - new_h) // 2
            src = src.crop((0, offset, src_w, offset + new_h))

        cropped_w, cropped_h = src.size
        if cropped_w > target_w and cropped_h > target_h:
            src = src.resize((target_w, target_h), Image.LANCZOS)
        # else: cropped source is already at or below the print target, so
        # leave it at native resolution rather than upscale it.

        buf = io.BytesIO()
        src.save(buf, format="JPEG", quality=quality)
        return (
            "data:image/jpeg;base64,"
            + base64.b64encode(buf.getvalue()).decode("ascii")
        )

    @api.model
    def _resize_max_dim(self, b64_source, max_dim=1200, quality=85):
        """Return JPEG base64 bytes downsized so neither side exceeds max_dim.

        Why this exists: the gallery-grid photos (page 3+) used to pass
        image_1920 straight through convert_image() with zero resizing --
        fine for the old image_512 source, but once that call site switched
        to the full 1920px source it meant embedding photos 2-4x larger (in
        each dimension) than the ~278pt print box ever needed, across up to
        18 photos per brochure. That's what pushed a 20-photo brochure's
        render time to ~26s and its PDF to ~30MB, long enough that visitors
        were abandoning the download (nginx logs it as HTTP 499) before it
        finished. 1200px covers a real 300dpi print at this box size with
        room to spare; downsizing before embedding is what actually cuts
        wkhtmltopdf's and the browser's work, not just the file size.
        """
        if not b64_source:
            return b''
        from PIL import Image
        raw = base64.b64decode(b64_source)
        # See _convert_to_jpeg_b64 for why this goes through a real file path.
        fd, tmp_path = tempfile.mkstemp(suffix=self._guess_suffix(raw))
        try:
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(raw)
            image = Image.open(tmp_path).convert('RGB')
            w, h = image.size
            if max(w, h) > max_dim:
                scale = max_dim / max(w, h)
                image = image.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
            buf = io.BytesIO()
            image.save(buf, format='JPEG', quality=quality)
            return base64.b64encode(buf.getvalue())
        except Exception:
            _logger.warning(
                "Could not resize image for luxury brochure gallery; skipping.",
                exc_info=True,
            )
            return b''
        finally:
            os.unlink(tmp_path)

    @api.model
    def _render_cover_full_bleed(self, b64_source, target_w=2480, target_h=3508):
        """Return a JPEG data URI of the cover photo pre-rendered at A4 size.

        target_w/target_h default to A4 at 300dpi (210mm/297mm) instead of
        the previous 794x1123 (A4 at 96dpi screen resolution) so the cover
        photo -- the single largest image in the brochure -- prints sharp
        rather than screen-soft. _render_crop_fit already refuses to upscale
        past the source's real resolution, so this is a ceiling, not a
        guarantee: a low-res source still won't be fabricated into 300dpi
        detail, it just won't be needlessly downsampled to 96dpi either.
        """
        return self._render_crop_fit(b64_source, target_w, target_h, quality=88)

    @api.model
    def _get_diamond_border_data_uri(self):
        """Return a base64 data URI for the Art Deco diamond border tile.

        wkhtmltopdf does not reliably render SVG as CSS background-image, so
        this generates a 20x200 PNG pixel-by-pixel with PIL (no external deps)
        and returns a data URI that can be used as `background: url(...)`.
        """
        from PIL import Image, ImageDraw

        w, h = 20, 200
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        gold = (201, 169, 97, 200)       # #c9a961 semi-opaque
        gold_light = (212, 175, 106, 120)  # #d4af6a lighter

        # Vertical rule down left side
        draw.rectangle([2, 0, 4, h], fill=gold)

        # Diamond pattern every 20px
        for y in range(0, h, 20):
            cx, cy = 11, y + 10
            # Outer diamond
            pts = [(cx, cy - 6), (cx + 5, cy), (cx, cy + 6), (cx - 5, cy)]
            draw.polygon(pts, fill=gold)
            # Inner dot
            draw.point((cx, cy), fill=gold_light)
            # Tiny horizontal rule connector
            draw.rectangle([5, cy - 1, 8, cy + 1], fill=gold)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return "data:image/png;base64," + b64

    @api.model
    def _get_monogram_svg_uri(self):
        """Return a data URI for the cover crest (crown glyph only).

        Returns a PNG data URI (not SVG) because wkhtmltopdf's QtWebKit
        engine does not reliably render inline SVG in <img> tags.
        PIL generates the PNG from the SVG-like description.

        The crown is generic line art.  An earlier revision also drew "AE"
        lettering under it -- a hardcoded monogram for one brand that was
        wrong on every other tenant and depended on fonts the rendering
        container does not ship -- so the lettering was removed.
        """
        from PIL import Image, ImageDraw

        size = 100
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx, cy = size // 2, size // 2
        gold = (201, 169, 97, 255)

        # Crown
        points = [
            (cx - 35, cy + 20),
            (cx - 28, cy - 12),
            (cx - 14, cy + 4),
            (cx, cy - 18),
            (cx + 14, cy + 4),
            (cx + 28, cy - 12),
            (cx + 35, cy + 20),
        ]
        draw.line(points, fill=gold, width=2)
        draw.line([(cx - 35, cy + 20), (cx + 35, cy + 20)], fill=gold, width=2)
        # Crown dots
        for dx, dy in [(-25, -8), (0, -20), (25, -8)]:
            draw.ellipse(
                [cx + dx - 3, cy + dy - 3, cx + dx + 3, cy + dy + 3],
                fill=gold,
            )

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return "data:image/png;base64," + b64

    @api.model
    def _get_gallery_pairs(self, images):
        """Return images as list of (left, right) tuples for two-column gallery.

        Each tuple contains two images or (image, None) for odd counts.
        This avoids QWeb's inability to conditionally open/close tr tags.
        """
        pairs = []
        raw = list(images)
        for i in range(0, len(raw), 2):
            left = raw[i]
            right = raw[i + 1] if i + 1 < len(raw) else None
            pairs.append((left, right))
        return pairs

    @api.model
    def _get_gallery_pages(self, images, per_page=6):
        """Chunk images into fixed-size groups, one group per gallery page.

        The gallery page previously rendered every image into one
        unbounded container (no fixed height, just min-height: 297mm), so
        wkhtmltopdf's continuous-flow rendering let it overflow past a
        single A4 page's worth of content for any property with more than
        a handful of images — producing extra physical PDF pages that
        never got the page's border/header chrome. Splitting into
        explicit per-page chunks up front means each chunk gets its own
        bounded `.gallery-page` div with a real `page-break-after`.
        """
        raw = list(images)
        return [raw[i:i + per_page] for i in range(0, len(raw), per_page)]



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
    def _brochure_label(self, prop):
        """Cover label for the document, derived from the record itself."""
        labels = {
            'residential': 'Private Residence Brochure',
            'commercial': 'Commercial Brochure',
            'industrial': 'Industrial Brochure',
            'land': 'Land Brochure',
        }
        return labels.get(prop.property_type, 'Property Brochure')

    @api.model
    def _story_excerpt(self, prop, limit=520):
        """Plain-text narrative for the interior page.

        Source: the unit's Description, else its project's Description --
        never static copy.  Trimmed at the last sentence (or word) boundary
        within ``limit`` characters so the fixed-height A4 page cannot
        overflow; the template hides the block when there is nothing real
        to show.
        """
        import re as _re
        import html as _html

        try:
            source = prop.description or prop.project_id.description or ''
            # Flatten block-by-block: split on block-level closing tags,
            # strip the remaining tags per segment and re-join the segments
            # with sentence boundaries.  A straight itertext() join glued
            # list items and paragraphs together ("wardrobes Spacious
            # suites"), which read as run-on copy in the PDF.
            text = ''
            if source:
                for seg in _re.split(
                    r'</(?:p|div|li|h[1-6]|tr|td|blockquote)\s*>|<br\s*/?>|\r?\n+',
                    source, flags=_re.I,
                ):
                    seg = _re.sub(r'<[^>]+>', ' ', seg)
                    seg = ' '.join(_html.unescape(seg).split())
                    if not seg:
                        continue
                    if not text:
                        text = seg
                    elif text[-1] in '.,;:!?':
                        text = text + ' ' + seg
                    else:
                        text = text + '. ' + seg
        except Exception:
            _logger.warning("Could not build the brochure story excerpt.", exc_info=True)
            return ''
        text = ' '.join((text or '').split())
        if len(text) <= limit:
            return text
        cut = text[:limit]
        for sep in ('. ', '; '):
            idx = cut.rfind(sep)
            if idx > limit // 2:
                return cut[:idx + 1].rstrip() + ' …'
        idx = cut.rfind(' ')
        return (cut[:idx] if idx > 0 else cut).rstrip() + ' …'

    @api.model
    def _qr_url_for(self, prop):
        """Absolute, real URL encoded into the brochure QR codes.

        A scan must land on a live page for this property.  The previous
        template encoded a bare reference ('BR1-201') or a brand
        placeholder ('AURELIA'), which resolved to dead text.  Published
        units link to their public page; anything else falls back to the
        project page and then the site root, so the QR is always
        scannable.  A per-record access token (``access_token`` field) is
        appended when the model carries one, so the scan grants the same
        access a tokenized share link would; nothing is fabricated when
        there is no token.
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

    # ── Clean-edition plate helpers (no cropping, no stretching) ─────
    @api.model
    def _lux_image_size(self, b64_source):
        """Return (width, height) of an image or None (never raises)."""
        from PIL import Image
        if not b64_source:
            return None
        raw = base64.b64decode(b64_source)
        fd, tmp_path = tempfile.mkstemp(suffix=self._guess_suffix(raw))
        try:
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(raw)
            return Image.open(tmp_path).size
        except Exception:
            _logger.warning("Could not read a brochure image size.", exc_info=True)
            return None
        finally:
            os.unlink(tmp_path)

    @api.model
    def _lux_plate_uri(self, b64_source, max_w, max_h=None, quality=92, as_png=False):
        """Data URI scaled to fit max_w x max_h at the native aspect ratio.

        Downscale-only (never upscales), never crops.  This is the single
        image rule of the clean edition: what the photo delivered is what
        the page shows.
        """
        if not b64_source:
            return ''
        from PIL import Image
        raw = base64.b64decode(b64_source)
        fd, tmp_path = tempfile.mkstemp(suffix=self._guess_suffix(raw))
        try:
            with os.fdopen(fd, 'wb') as tmp:
                tmp.write(raw)
            image = Image.open(tmp_path)
            w, h = image.size
            scale = (max_w / float(w)) if w else 1.0
            if max_h and h:
                scale = min(scale, max_h / float(h))
            scale = min(scale, 1.0)  # never upscale
            if scale < 0.999:
                image = image.resize((max(1, int(round(w * scale))),
                                      max(1, int(round(h * scale)))), Image.LANCZOS)
            buf = io.BytesIO()
            if as_png:
                image.convert('RGBA').save(buf, format='PNG')
                mime = 'image/png'
            else:
                image.convert('RGB').save(buf, format='JPEG', quality=quality)
                mime = 'image/jpeg'
            return 'data:%s;base64,%s' % (mime, base64.b64encode(buf.getvalue()).decode('ascii'))
        except Exception:
            _logger.warning("Could not render a brochure plate; skipping.", exc_info=True)
            return ''
        finally:
            os.unlink(tmp_path)

    @api.model
    def _lux_cover_hero(self, prop):
        """Cover hero: the whole photo, never cropped.

        Wide photos (ratio >= 1.64) span the full page width; taller photos
        are height-bound to 128mm and centred.  Both keep the native
        aspect, so nothing is cut away and the pixels spread over less
        physical area than the old full-bleed crop (which sliced a 16:9
        render down to ~760px across a full A4 page and looked pixelated).
        """
        b64 = prop.image_1920
        size = self._lux_image_size(b64)
        if not size or not size[0] or not size[1]:
            return None
        ratio = size[0] / float(size[1])
        if ratio >= 1.64:
            uri = self._lux_plate_uri(b64, max_w=2480, quality=92)
            return {'uri': uri, 'wide': True} if uri else None
        uri = self._lux_plate_uri(b64, max_w=2480, max_h=1512, quality=92)
        return {'uri': uri, 'wide': False} if uri else None

    @api.model
    def _lux_floorplan(self, prop):
        """Floorplan for the dedicated plan page: whole image, no crop.

        Prefers the unit's own floor_plan field, else the first gallery
        image whose name says floor/plan.  PNG sources stay PNG (crisp
        diagram lines); JPEG sources are re-encoded at quality 95.
        """
        b64 = prop.floor_plan
        caption = prop.floor_plan_filename or ''
        if not b64:
            for img in prop.image_ids:
                nm = (img.name or '')
                if 'floor' in nm.lower() or 'plan' in nm.lower():
                    b64, caption = img.image_1920, nm
                    break
        if not b64:
            return None
        as_png = self._guess_suffix(base64.b64decode(b64)) == '.png'
        size = self._lux_image_size(b64)
        # A portrait plan at full plate width would run into the footer; bound
        # it by height instead (158mm keeps header + mat + caption + footer
        # inside one A4 page).  Landscape plans stay width-bound.
        by_height = bool(size and size[0] and (166.0 * size[1] / size[0]) > 158.0)
        if by_height:
            uri = self._lux_plate_uri(b64, max_w=2480, max_h=1900, quality=95, as_png=as_png)
        else:
            uri = self._lux_plate_uri(b64, max_w=2240, quality=95, as_png=as_png)
        if not uri:
            return None
        caption = (caption or 'Floor Plan').strip()
        low = caption.lower()
        for pref in ('floor plan - ', 'floor plan \u2014 ', 'floor plan \u2013 ',
                     'floor plan: ', 'floor plan '):
            if low.startswith(pref):
                caption = caption[len(pref):].strip()
                break
        return {'uri': uri, 'caption': caption or 'Floor Plan', 'by_height': by_height}

    @api.model
    def _lux_photo_plates(self, prop):
        """Gallery photo plates (floor plans excluded - they have their page)."""
        plates = []
        for img in prop.image_ids:
            nm = (img.name or '')
            if 'floor' in nm.lower() or 'plan' in nm.lower():
                continue
            size = self._lux_image_size(img.image_1920)
            uri = self._lux_plate_uri(img.image_1920, max_w=2100, quality=90)
            if uri and size:
                plates.append({'uri': uri, 'caption': nm, 'w': size[0], 'h': size[1]})
        return plates

    @api.model
    def _lux_gallery_layout(self, plates, photo_w_mm=174.0, budget_mm=259.0):
        """Pack plates into pages by real display height (native aspect).

        Each plate shows at photo_w_mm wide, so its page height is known
        before rendering and pages fill greedily up to the A4 content
        budget - instead of forcing a fixed grid that cropped tall images.
        """
        pages, page, used = [], [], 0.0
        for plate in plates:
            w = plate.get('w') or 1
            h = plate.get('h') or 1
            h_mm = photo_w_mm * h / float(w)
            cost = h_mm + 22.0  # plate padding/border + caption + gap
            if page and used + cost > budget_mm:
                pages.append(page)
                page, used = [], 0.0
            page.append(plate)
            used += cost
        if page:
            pages.append(page)
        return pages

    @api.model
    def _lux_facts(self, prop):
        """At-a-Glance rows for the residence page (record data only)."""
        def sel(fname):
            field = prop._fields[fname]
            return dict(field.selection).get(prop[fname], prop[fname])

        rows = []

        def add(label, value):
            if value not in (False, None, ''):
                rows.append({'label': label, 'value': value})

        add('Type', sel('property_type'))
        add('Status', sel('state'))
        add('Bedrooms', prop.bedrooms)
        add('Bathrooms', prop.bathrooms)
        if prop.area:
            add('Built-Up Area', '{:,.0f} sq ft'.format(prop.area))
        add('Floor', prop.floor)
        add('Project', prop.project_id.name)
        add('Building / Tower', prop.sub_project_id.name)
        add('Region', prop.region_id.name)
        return rows

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env["property.details"].browse(docids)

        # Pre-build expensive data URIs once
        border_uri = self._get_diamond_border_data_uri()
        monogram_uri = self._get_monogram_svg_uri()

        # wkhtmltopdf renders from a local file with no browser context, so
        # relative URLs (e.g. "/report/barcode/...") never resolve: the QR
        # <img> silently fails to load and the PDF shows its alt text
        # instead. Build an absolute URL so the barcode image actually loads.
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")

        # Pre-build a full-bleed cover image per property. Doing it here (not
        # inside the t-foreach) would cache once for the multi-property case
        # too, but for now (most reports are single-property) the inner loop
        # is fine and easier to read.
        def _cover_for(prop):
            return self._render_cover_full_bleed(prop.image_1920)

        return {
            "doc_ids": docids,
            "doc_model": "property.details",
            "docs": docs,
            "convert_image": self._convert_to_jpeg_b64,
            "trakheesi_qr_uri": self._trakheesi_qr_uri,
            "diamond_border_uri": border_uri,
            "monogram_uri": monogram_uri,
            "quote_plus": quote_plus,
            "base_url": base_url,
            "gallery_pages": self._get_gallery_pages,
            "crop_fit_uri": self._render_crop_fit,
            "resize_image": self._resize_max_dim,
            # Set both here AND via <t t-set> inside the template: web.html_container
            # resolves class="container" vs "container-fluid" from the binding
            # context, and depending on Odoo version the t-set inside a t-foreach
            # is either local to the iteration or hoisted -- making it explicit
            # in the report_values dict guarantees body.class becomes
            # container-fluid so the 210mm page divs are never clipped to the
            # Bootstrap .container max-width of 540px (or 720/960/1140 at
            # wider breakpoints).
            "full_width": True,
            "cover_image_uri_for": _cover_for,
            "brochure_label_for": self._brochure_label,
            "story_excerpt_for": self._story_excerpt,
            "qr_url_for": self._qr_url_for,
            "cover_hero_for": self._lux_cover_hero,
            "floorplan_for": self._lux_floorplan,
            "photo_plates_for": self._lux_photo_plates,
            "gallery_layout_for": self._lux_gallery_layout,
            "facts_for": self._lux_facts,
        }
