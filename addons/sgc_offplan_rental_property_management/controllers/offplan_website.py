from odoo import http, _
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class OffplanWebsiteController(http.Controller):

    @http.route([
        '/offplan/properties',
        '/properties',
    ], type='http', auth='public', website=True, sitemap=True)
    def property_listing(self, **kwargs):
        """Public listing page for offplan properties (property.details model)"""
        try:
            domain = [('is_published_website', '=', True)]
            search = kwargs.get('search')
            if search:
                domain += ['|', ('name', 'ilike', search), ('city', 'ilike', search)]
            property_type = kwargs.get('property_type')
            if property_type:
                domain += [('property_type', '=', property_type)]
            state = kwargs.get('state')
            if state:
                domain += [('state', '=', state)]
            min_price = kwargs.get('min_price')
            if min_price:
                domain += [('sale_price', '>=', float(min_price))]
            max_price = kwargs.get('max_price')
            if max_price:
                domain += [('sale_price', '<=', float(max_price))]

            order = 'website_featured desc, website_published_date desc'
            properties = request.env['property.details'].sudo().search(domain, order=order)
            property_types = dict(
                request.env['property.details']._fields['property_type'].selection
            )
            states = dict(
                request.env['property.details']._fields['state'].selection
            )
            return request.render('sgc_offplan_rental_property_management.offplan_property_listing', {
                'properties': properties,
                'property_types': property_types,
                'states': states,
                'filters': kwargs,
                'search_term': kwargs.get('search'),
            })
        except Exception as e:
            _logger.error("Offplan listing error: %s", str(e), exc_info=True)
            return request.render('website.page_404')

    @http.route([
        '/offplan/property/<int:property_id>',
        '/property/<int:property_id>',
    ], type='http', auth='public', website=True, sitemap=True)
    def property_detail(self, property_id, **kwargs):
        """Public detail page for an offplan property"""
        try:
            property = request.env['property.details'].sudo().browse(property_id)
            if not property.exists() or not property.is_published_website:
                return request.render('website.page_404')
            property.increment_website_views()
            similar = request.env['property.details'].sudo().search([
                ('is_published_website', '=', True),
                ('id', '!=', property.id),
                '|', ('project_id', '=', property.project_id.id),
                     ('property_type', '=', property.property_type),
            ], limit=4)
            return request.render(
                'sgc_offplan_rental_property_management.offplan_property_detail', {
                    'property': property,
                    'similar_properties': similar,
                })
        except Exception as e:
            _logger.error("Offplan detail error: %s", str(e), exc_info=True)
            return request.render('website.page_404')

    @http.route([
        '/offplan/projects',
        '/projects',
    ], type='http', auth='public', website=True, sitemap=True)
    def project_listing(self, **kwargs):
        """Public listing page for projects"""
        try:
            PropertyProject = request.env['property.project'].sudo()
            projects = PropertyProject.search([])
            return request.render(
                'sgc_offplan_rental_property_management.offplan_project_listing', {
                    'projects': projects,
                })
        except Exception as e:
            _logger.error("Project listing error: %s", str(e), exc_info=True)
            return request.render('website.page_404')

    @http.route('/offplan/property/inquiry', type='jsonrpc', auth='public', website=True, methods=['POST'])
    def property_inquiry(self, **kwargs):
        """Gated lead capture — creates inquiry, returns brochure download URL on success."""
        try:
            if not kwargs.get('name') or not kwargs.get('email'):
                return {'success': False, 'error': _('Name and email are required.')}
            if not kwargs.get('property_id'):
                return {'success': False, 'error': _('Property is required.')}

            property_id = int(kwargs['property_id'])
            property_rec = request.env['property.details'].sudo().browse(property_id)
            if not property_rec.exists():
                return {'success': False, 'error': _('Property not found.')}

            inquiry = request.env['property.website.inquiry'].sudo().create({
                'property_id': property_id,
                'name': kwargs.get('name'),
                'email': kwargs.get('email'),
                'phone': kwargs.get('phone', ''),
                'message': kwargs.get('message', ''),
                'property_url': request.httprequest.url,
            })
            property_rec.sudo().write({'website_inquiry_count': property_rec.website_inquiry_count + 1})

            # property.website.inquiry only feeds this property's own smart
            # button (action_view_website_inquiries) -- it never reached the
            # CRM pipeline, so sales saw zero leads from this form even
            # though visitors were submitting it. A crm.lead is what actually
            # shows up in the leads pool.
            request.env['crm.lead'].sudo().create({
                'name': _('Property inquiry: %s') % (property_rec.name or _('Property #%s') % property_id),
                'contact_name': kwargs.get('name'),
                'email_from': kwargs.get('email'),
                'phone': kwargs.get('phone', ''),
                'description': kwargs.get('message') or _(
                    'Website inquiry for "%s" (property.details id=%s).'
                ) % (property_rec.name or '', property_id),
            })

            # Live-render the luxury brochure rather than pointing at the
            # `brochure` binary field, which nothing in the codebase ever
            # populates -- that field only ever holds a manually-uploaded
            # override, so the download link was broken for every property
            # unless staff had separately uploaded a PDF by hand.
            download_url = False
            if property_rec.is_published_website:
                download_url = f'/offplan/property/{property_id}/brochure.pdf'
            elif property_rec.brochure:
                download_url = f'/web/content/property.details/{property_id}/brochure?download=true'
            elif property_rec.floor_plan:
                download_url = f'/web/content/property.details/{property_id}/floor_plan?download=true'

            return {
                'success': True,
                'id': inquiry.id,
                'download_url': download_url,
            }
        except Exception as e:
            _logger.error("Property inquiry error: %s", str(e), exc_info=True)
            return {'success': False, 'error': str(e)}

    @http.route('/offplan/property/<int:property_id>/brochure.pdf', type='http', auth='public', website=True)
    def property_brochure_pdf(self, property_id, **kwargs):
        """Live-render the luxury brochure PDF for public, gated download."""
        property_rec = request.env['property.details'].sudo().browse(property_id)
        if not property_rec.exists() or not property_rec.is_published_website:
            return request.not_found()
        try:
            pdf_content, filename = property_rec.render_luxury_brochure_pdf()
        except Exception:
            _logger.exception('Failed to render property brochure PDF for property.details id=%s', property_id)
            return request.not_found()
        headers = [
            ('Content-Type', 'application/pdf'),
            ('Content-Length', len(pdf_content)),
            ('Content-Disposition', 'attachment; filename="%s"' % filename),
        ]
        return request.make_response(pdf_content, headers=headers)

    @http.route(['/offplan/project/<int:project_id>'], type='http', auth='public', website=True, sitemap=True)
    def project_detail(self, project_id, **kwargs):
        """Public detail page for a project"""
        try:
            project = request.env['property.project'].sudo().browse(project_id)
            if not project.exists():
                return request.render('website.page_404')
            properties = request.env['property.details'].sudo().search([
                ('project_id', '=', project.id),
                ('is_published_website', '=', True),
            ])
            return request.render(
                'sgc_offplan_rental_property_management.offplan_project_detail', {
                    'project': project,
                    'properties': properties,
                })
        except Exception as e:
            _logger.error("Project detail error: %s", str(e), exc_info=True)
            return request.render('website.page_404')
