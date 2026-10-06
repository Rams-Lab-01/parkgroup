from datetime import date
from dateutil.relativedelta import relativedelta
import base64
import io
import xlsxwriter

from odoo import http, _
from odoo.http import request
from odoo.exceptions import ValidationError


class CustomerPortal(http.Controller):

    # ── My Properties ─────────────────────────────────────────────────

    @http.route(['/my/properties'], type='http', auth='user', website=True)
    def portal_my_properties(self, **kwargs):
        """List properties owned/rented by the current customer."""
        user = request.env.user
        partner = user.partner_id
        properties = request.env['property.details'].sudo().search([
            '|', ('owner_id', '=', partner.id),
                  ('landlord_id', '=', partner.id),
        ])
        # Also find properties via contracts
        sale_contracts = request.env['sale.contract'].sudo().search([
            ('buyer_id', '=', partner.id),
        ])
        rent_contracts = request.env['rent.contract'].sudo().search([
            ('tenant_id', '=', partner.id),
        ])
        contract_property_ids = set()
        for c in sale_contracts:
            if c.property_id:
                contract_property_ids.add(c.property_id.id)
        for c in rent_contracts:
            if c.property_id:
                contract_property_ids.add(c.property_id.id)
        if contract_property_ids:
            extra = request.env['property.details'].sudo().browse(
                list(contract_property_ids)
            )
            properties = (properties + extra)
        
        # Get tenancy details and vendor bookings for the user's properties
        # for display in the property detail tabs (legacy models)
        property_ids = properties.ids
        tenancy_details = request.env['tenancy.details'].sudo().search([
            ('property_id', 'in', property_ids)
        ]) if property_ids else request.env['tenancy.details']
        vendor_bookings = request.env['property.vendor'].sudo().search([
            ('property_id', 'in', property_ids)
        ]) if property_ids else request.env['property.vendor']
        
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_properties', {
                'properties': properties,
                'sale_contracts': sale_contracts,
                'rent_contracts': rent_contracts,
                'tenancy_details': tenancy_details,
                'vendor_bookings': vendor_bookings,
                'page_name': 'my_properties',
            }
        )

    @http.route([
        '/my/property/<int:property_id>',
        '/my/property/<int:property_id>/<string:tab>',
    ], type='http', auth='user', website=True)
    def portal_my_property_detail(self, property_id, tab='overview', **kwargs):
        """Detail view for a customer's property with tabs."""
        partner = request.env.user.partner_id
        if not self._check_user_can_access_property(property_id, partner):
            return request.render('website.page_404')
        property = request.env['property.details'].sudo().browse(property_id)
        if not property.exists():
            return request.render('website.page_404')
        sale_contracts = request.env['sale.contract'].sudo().search([
            ('property_id', '=', property_id),
            ('buyer_id', '=', request.env.user.partner_id.id),
        ])
        rent_contracts = request.env['rent.contract'].sudo().search([
            ('property_id', '=', property_id),
            ('tenant_id', '=', request.env.user.partner_id.id),
        ])
        # Also load legacy contract models for bridge display
        tenancy_details = request.env['tenancy.details'].sudo().search([
            ('property_id', '=', property_id),
            ('tenant_id', '=', request.env.user.partner_id.id),
        ])
        vendor_bookings = request.env['property.vendor'].sudo().search([
            ('property_id', '=', property_id),
            ('customer_id', '=', request.env.user.partner_id.id),
        ])
        # IDOR guard: owners/landlords see all property invoices;
        # tenants/buyers see only invoices addressed to them.
        is_owner = property.owner_id == partner or property.landlord_id == partner
        if is_owner:
            invoices = request.env['account.move'].sudo().search([
                '|', ('tenancy_property_id', '=', property_id),
                     ('sold_property_id', '=', property_id),
            ])
        else:
            invoices = request.env['account.move'].sudo().search([
                '&',
                ('partner_id', '=', partner.id),
                '|',
                ('tenancy_property_id', '=', property_id),
                ('sold_property_id', '=', property_id),
            ])
        maintenance = request.env['maintenance.request'].sudo().search([
            ('property_id', '=', property_id),
        ])
        installments = request.env['sale.contract.installment'].sudo().search([
            ('contract_id', 'in', sale_contracts.ids),
        ])
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_property_detail', {
                'property': property,
                'sale_contracts': sale_contracts,
                'rent_contracts': rent_contracts,
                'tenancy_details': tenancy_details,
                'vendor_bookings': vendor_bookings,
                'invoices': invoices,
                'maintenance_requests': maintenance,
                'installments': installments,
                'tab': tab,
                'page_name': 'my_properties',
            }
        )

    # ── Contracts ──────────────────────────────────────────────────────────

    @http.route(['/my/contracts'], type='http', auth='user', website=True)
    def portal_my_contracts(self, **kwargs):
        """List all sale and rent contracts for the current customer."""
        partner = request.env.user.partner_id
        sale_contracts = request.env['sale.contract'].sudo().search([
            ('buyer_id', '=', partner.id),
        ])
        rent_contracts = request.env['rent.contract'].sudo().search([
            ('tenant_id', '=', partner.id),
        ])
        
        # Get property IDs for the contracts to fetch related tenancy details and vendor bookings
        property_ids = set()
        for c in sale_contracts:
            if c.property_id:
                property_ids.add(c.property_id.id)
        for c in rent_contracts:
            if c.property_id:
                property_ids.add(c.property_id.id)
        
        # Get tenancy details and vendor bookings for the user's contracted properties
        # for display in the contract detail tabs (legacy models)
        tenancy_details = request.env['tenancy.details'].sudo().search([
            ('property_id', 'in', list(property_ids))
        ]) if property_ids else request.env['tenancy.details']
        vendor_bookings = request.env['property.vendor'].sudo().search([
            ('property_id', 'in', list(property_ids))
        ]) if property_ids else request.env['property.vendor']
        
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_contracts', {
                'sale_contracts': sale_contracts,
                'rent_contracts': rent_contracts,
                'tenancy_details': tenancy_details,
                'vendor_bookings': vendor_bookings,
                'page_name': 'my_contracts',
            }
        )

    @http.route([
        '/my/contract/<string:model>/<int:contract_id>',
    ], type='http', auth='user', website=True)
    def portal_my_contract_detail(self, model, contract_id, **kwargs):
        """Detail view for a specific contract."""
        partner = request.env.user.partner_id
        if model == 'sale':
            contract = request.env['sale.contract'].sudo().browse(contract_id)
            if not contract.exists() or contract.buyer_id.id != partner.id:
                return request.render('website.page_404')
        elif model == 'rent':
            contract = request.env['rent.contract'].sudo().browse(contract_id)
            if not contract.exists() or (
                contract.tenant_id.id != partner.id and
                contract.landlord_id.id != partner.id
            ):
                return request.render('website.page_404')
        else:
            return request.render('website.page_404')
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_contract_detail', {
                'contract': contract,
                'model': model,
                'page_name': 'my_contracts',
            }
        )

    # ── Invoices & Payments ────────────────────────────────────────────────

    @http.route(['/my/invoices'], type='http', auth='user', website=True)
    def portal_my_invoices(self, **kwargs):
        """List invoices for the current customer."""
        partner = request.env.user.partner_id
        invoices = request.env['account.move'].sudo().search([
            ('partner_id', '=', partner.id),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
        ], order='invoice_date desc')
        credit_notes = invoices.filtered(lambda i: i.move_type == 'out_refund')
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_invoices', {
                'invoices': invoices,
                'credit_notes': credit_notes,
                'page_name': 'my_invoices',
            }
        )

    @http.route(['/my/invoice/<int:invoice_id>'], type='http', auth='user', website=True)
    def portal_my_invoice_detail(self, invoice_id, **kwargs):
        """Invoice detail with payment link."""
        partner = request.env.user.partner_id
        invoice = request.env['account.move'].sudo().browse(invoice_id)
        if not invoice.exists():
            return request.not_found()
        ids_equal = invoice.partner_id.id == partner.id
        if not ids_equal:
            return request.not_found()
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_invoice_detail', {
                'invoice': invoice,
                'page_name': 'my_invoices',
            }
        )

    @http.route(['/my/invoice/<int:invoice_id>/pay'], type='http', auth='user', website=True)
    def portal_my_invoice_pay(self, invoice_id, **kwargs):
        """Redirect to the standard invoice portal payment page.

        The stock ``account_payment`` invoice page (``/my/invoices/<id>``)
        renders the working "Pay Now" form (transaction route
        ``/invoice/transaction/<id>``) which authenticates the amount via the
        invoice access token and reconciles the resulting payment against this
        invoice. ``payment=True`` auto-opens the payment dialog. The previous
        ``/payment/pay?invoice_id=...`` target ignored ``invoice_id`` (that
        route takes ``amount``/``partner_id``, not an invoice), so it neither
        charged the correct amount nor reconciled against the invoice.
        """
        partner = request.env.user.partner_id
        invoice = request.env['account.move'].sudo().browse(invoice_id)
        if not invoice.exists() or invoice.partner_id.id != partner.id:
            return request.render('website.page_404')
        return request.redirect(invoice.get_portal_url(query_string='&payment=True'))

    @http.route(['/my/credit-notes'], type='http', auth='user', website=True)
    def portal_my_credit_notes(self, **kwargs):
        """List credit notes/refunds for the current customer."""
        partner = request.env.user.partner_id
        credit_notes = request.env['account.move'].sudo().search([
            ('partner_id', '=', partner.id),
            ('move_type', '=', 'out_refund'),
        ], order='invoice_date desc')
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_credit_notes', {
                'credit_notes': credit_notes,
                'page_name': 'my_invoices',
            }
        )

    # ── Maintenance ────────────────────────────────────────────────────────

    def _get_user_property_ids(self, partner):
        """Return all property IDs this portal user has rights to.

        A portal user may own (owner_id), landlord (landlord_id), or be an
        active tenant of a property (via rent.contract or tenancy.details).
        """
        direct = request.env['property.details'].sudo().search([
            '|', ('owner_id', '=', partner.id),
                 ('landlord_id', '=', partner.id),
        ]).ids
        lease_ids = set(
            request.env['rent.contract'].sudo().search([
                ('tenant_id', '=', partner.id),
                ('state', '=', 'active'),
            ]).mapped('property_id').ids
        )
        tenancy_ids = set(
            request.env['tenancy.details'].sudo().search([
                ('tenant_id', '=', partner.id),
                ('state', '=', 'active'),
            ]).mapped('property_id').ids
        )
        return list(set(direct) | lease_ids | tenancy_ids)

    def _check_user_can_access_property(self, property_id, partner):
        if not property_id:
            return False
        return property_id in self._get_user_property_ids(partner)

    @http.route(['/my/maintenance'], type='http', auth='user', website=True)
    def portal_my_maintenance(self, **kwargs):
        """List maintenance requests for the current customer."""
        partner = request.env.user.partner_id
        property_ids = self._get_user_property_ids(partner)
        maintenance = request.env['maintenance.request'].sudo().search([
            '|', ('tenant_id', '=', partner.id),
                 ('property_id', 'in', property_ids),
        ], order='create_date desc')
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_maintenance', {
                'maintenance_requests': maintenance,
                'page_name': 'my_maintenance',
            }
        )

    @http.route([
        '/my/maintenance/new',
        '/my/maintenance/new/<int:property_id>',
    ], type='http', auth='user', website=True)
    def portal_my_maintenance_new(self, property_id=None, **kwargs):
        """Create a new maintenance request."""
        partner = request.env.user.partner_id
        property_ids = self._get_user_property_ids(partner)
        properties = request.env['property.details'].sudo().browse(property_ids)
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_maintenance_form', {
                'properties': properties,
                'selected_property_id': property_id if property_id and property_id in property_ids else None,
                'error': kwargs.get('error'),
                'page_name': 'my_maintenance',
            }
        )

    @http.route(['/my/maintenance/submit'], type='http', auth='user', website=True, methods=['POST'])
    def portal_my_maintenance_submit(self, **kwargs):
        """Submit a new maintenance request."""
        partner = request.env.user.partner_id
        raw_pid = kwargs.get('property_id')
        property_id = int(raw_pid) if raw_pid else False
        if not self._check_user_can_access_property(property_id, partner):
            _logger.warning(
                "Portal user %s attempted to submit maintenance for unauthorized property %s",
                partner.id, property_id)
            return request.redirect('/my/maintenance/new')
        try:
            vals = {
                'name': kwargs.get('subject', 'Maintenance Request'),
                'description': kwargs.get('description', ''),
                'user_id': request.env.user.id,
                'property_id': property_id,
                'tenant_id': partner.id,
            }
            request.env['maintenance.request'].sudo().create(vals)
            return request.redirect('/my/maintenance')
        except Exception as e:
            _logger.error("Maintenance submit error: %s", str(e), exc_info=True)
            return request.redirect('/my/maintenance/new?error=1')

    @http.route(['/my/maintenance/<int:maintenance_id>'], type='http', auth='user', website=True)
    def portal_my_maintenance_detail(self, maintenance_id, **kwargs):
        """Maintenance request detail."""
        partner = request.env.user.partner_id
        maintenance = request.env['maintenance.request'].sudo().browse(maintenance_id)
        if not maintenance.exists():
            return request.render('website.page_404')
        if maintenance.tenant_id.id != partner.id and not self._check_user_can_access_property(
                maintenance.property_id.id, partner):
            return request.render('website.page_404')
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_maintenance_detail', {
                'maintenance': maintenance,
                'page_name': 'my_maintenance',
            }
        )

    # ── Statements ─────────────────────────────────────────────────────────

    @http.route(['/my/statements'], type='http', auth='user', website=True)
    def portal_my_statements(self, **kwargs):
        """Statement of account page."""
        partner = request.env.user.partner_id
        properties = request.env['property.details'].sudo().search([
            '|', ('owner_id', '=', partner.id),
                 ('landlord_id', '=', partner.id),
        ])
        invoices = request.env['account.move'].sudo().search([
            ('partner_id', '=', partner.id),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
        ])
        maintenance_invoices = invoices.filtered(lambda i: i.maintenance_request_id)
        total_outstanding = sum(invoices.filtered(
            lambda i: i.payment_state in ('not_paid', 'partial')
        ).mapped('amount_total'))
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_statements', {
                'properties': properties,
                'invoices': invoices,
                'maintenance_invoices': maintenance_invoices,
                'total_outstanding': total_outstanding,
                'page_name': 'my_statements',
            }
        )

    # ── Tenant helpers ─────────────────────────────────────────────────────

    _LEASE_MODELS = {
        'rent_contract': 'rent.contract',
        'tenancy_details': 'tenancy.details',
    }

    def _get_tenant_active_lease(self, partner):
        """Return the tenant's active lease, preferring rent.contract over tenancy.details."""
        lease = request.env['rent.contract'].sudo().search([
            ('tenant_id', '=', partner.id),
            ('state', '=', 'active'),
        ], limit=1)
        if lease:
            return lease
        return request.env['tenancy.details'].sudo().search([
            ('tenant_id', '=', partner.id),
            ('state', '=', 'active'),
        ], limit=1)

    def _get_tenant_active_property_ids(self, partner):
        """Return property ids tied to the tenant's active leases in either model."""
        rent = request.env['rent.contract'].sudo().search([
            ('tenant_id', '=', partner.id),
            ('state', '=', 'active'),
        ])
        tenancy = request.env['tenancy.details'].sudo().search([
            ('tenant_id', '=', partner.id),
            ('state', '=', 'active'),
        ])
        ids = set(rent.mapped('property_id').ids) | set(tenancy.mapped('property_id').ids)
        return list(ids)

    # ── Tenant Dashboard ───────────────────────────────────────────────────

    @http.route(['/my/dashboard'], type='http', auth='user', website=True)
    def portal_tenant_dashboard(self, **kwargs):
        """Tenant-oriented landing page with lease and account summary."""
        partner = request.env.user.partner_id
        lease = self._get_tenant_active_lease(partner)
        lease_end_date = lease.end_date if lease else False
        days_remaining = (lease_end_date - date.today()).days if lease_end_date else None
        maintenance = request.env['maintenance.request'].sudo().search([
            ('tenant_id', '=', partner.id),
        ])
        open_maintenance_count = len(
            maintenance.filtered(lambda m: not m.stage_id.fold))
        invoices = request.env['account.move'].sudo().search([
            ('partner_id', '=', partner.id),
            ('move_type', 'in', ['out_invoice', 'out_refund']),
            ('payment_state', 'in', ['not_paid', 'partial']),
        ])
        total_outstanding = sum(invoices.mapped('amount_residual'))
        return request.render(
            'sgc_offplan_rental_property_management.portal_tenant_dashboard', {
                'lease': lease,
                'lease_end_date': lease_end_date,
                'days_remaining': days_remaining,
                'open_maintenance_count': open_maintenance_count,
                'total_outstanding': total_outstanding,
                'page_name': 'my_dashboard',
            }
        )

    # ── Lease ──────────────────────────────────────────────────────────────

    @http.route(['/my/lease'], type='http', auth='user', website=True)
    def portal_my_lease(self, **kwargs):
        """List the tenant's leases across both lease models."""
        partner = request.env.user.partner_id
        rent_contracts = request.env['rent.contract'].sudo().search([
            ('tenant_id', '=', partner.id),
        ])
        tenancy_details = request.env['tenancy.details'].sudo().search([
            ('tenant_id', '=', partner.id),
        ])
        leases = []
        for lease in rent_contracts:
            leases.append({'record': lease, 'model': 'rent_contract'})
        for lease in tenancy_details:
            leases.append({'record': lease, 'model': 'tenancy_details'})
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_lease', {
                'leases': leases,
                'page_name': 'my_lease',
            }
        )

    @http.route([
        '/my/lease/<string:model>/<int:lease_id>',
    ], type='http', auth='user', website=True)
    def portal_my_lease_detail(self, model, lease_id, **kwargs):
        """Detail view for a tenant's lease in either model."""
        model_name = self._LEASE_MODELS.get(model)
        if not model_name:
            return request.render('website.page_404')
        lease = request.env[model_name].sudo().browse(lease_id)
        if not lease.exists() or lease.tenant_id.id != request.env.user.partner_id.id:
            return request.render('website.page_404')
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_lease_detail', {
                'lease': lease,
                'model': model,
                'page_name': 'my_lease',
            }
        )

    @http.route([
        '/my/lease/<string:model>/<int:lease_id>/renew',
    ], type='http', auth='user', website=True, methods=['POST'])
    def portal_my_lease_renew(self, model, lease_id, **kwargs):
        """Request lease renewal for a tenant's lease."""
        model_name = self._LEASE_MODELS.get(model)
        if not model_name:
            return request.render('website.page_404')
        lease = request.env[model_name].sudo().browse(lease_id)
        if not lease.exists() or lease.tenant_id.id != request.env.user.partner_id.id:
            return request.render('website.page_404')
        if model == 'rent_contract':
            lease.action_request_renewal()
        else:
            _logger.warning(
                "Renewal requested for tenancy.details %s which has no renewal support.",
                lease_id)
        return request.redirect('/my/lease/%s/%s' % (model, lease_id))

    # ── Documents ──────────────────────────────────────────────────────────

    @http.route(['/my/documents'], type='http', auth='user', website=True)
    def portal_my_documents(self, **kwargs):
        """List portal-visible documents for the tenant's active properties."""
        partner = request.env.user.partner_id
        property_ids = self._get_tenant_active_property_ids(partner)
        documents = request.env['property.documents'].sudo().search([
            ('portal_visible', '=', True),
            ('property_id', 'in', property_ids),
        ])
        properties = request.env['property.details'].sudo().browse(property_ids)
        doc_categories = request.env['property.documents']._fields['doc_category'].selection
        return request.render(
            'sgc_offplan_rental_property_management.portal_my_documents', {
                'documents': documents,
                'properties': properties,
                'doc_categories': doc_categories,
                'error': kwargs.get('error'),
                'page_name': 'my_documents',
            }
        )

    @http.route(['/my/documents/upload'], type='http', auth='user', website=True, methods=['POST'])
    def portal_my_documents_upload(self, **kwargs):
        """Upload a document against one of the tenant's active properties."""
        partner = request.env.user.partner_id
        property_id = int(kwargs.get('property_id', 0)) if kwargs.get('property_id') else False
        allowed_ids = self._get_tenant_active_property_ids(partner)
        if not property_id or property_id not in allowed_ids:
            return request.redirect('/my/documents?error=1')
        upload = request.httprequest.files.get('document')
        if not upload:
            return request.redirect('/my/documents?error=1')
        file_data = base64.b64encode(upload.read())
        try:
            request.env['property.documents'].sudo().create({
                'property_id': property_id,
                'document': file_data,
                'file_name': upload.filename,
                'doc_category': kwargs.get('doc_category', 'other'),
                'portal_visible': True,
                'uploaded_by_partner_id': partner.id,
                'approval_state': 'pending',
            })
            return request.redirect('/my/documents')
        except ValidationError as e:
            _logger.warning("Document upload validation failed: %s", str(e))
            return request.redirect('/my/documents?error=1')

    # ── Landlord helpers ───────────────────────────────────────────────────

    def _get_landlord_properties(self, partner):
        """Return properties owned by the given landlord partner."""
        return request.env['property.details'].sudo().search([
            ('landlord_id', '=', partner.id),
        ])

    def _get_landlord_property_ids(self, partner):
        """Return landlord's property ids (convenience wrapper)."""
        return self._get_landlord_properties(partner).ids

    # ── Landlord Dashboard ─────────────────────────────────────────────────

    @http.route(['/my/portfolio'], type='http', auth='user', website=True)
    def portal_landlord_portfolio(self, **kwargs):
        """Landlord dashboard with property, occupancy, lease and income KPIs."""
        partner = request.env.user.partner_id
        properties = self._get_landlord_properties(partner)
        property_ids = properties.ids

        state_groups = request.env['property.details'].sudo()._read_group(
            [('landlord_id', '=', partner.id)],
            groupby=['state'],
            aggregates=['__count'])
        occupancy = {state: count for state, count in state_groups}

        rent_active = request.env['rent.contract'].sudo().search_count([
            ('landlord_id', '=', partner.id),
            ('state', '=', 'active'),
        ])
        tenancy_active = request.env['tenancy.details'].sudo().search_count([
            ('landlord_id', '=', partner.id),
            ('state', '=', 'active'),
        ])

        pending_maintenance = request.env['maintenance.request'].sudo().search_count([
            ('landlord_id', '=', partner.id),
            ('landlord_approval_state', '=', 'pending'),
        ])

        month_start = date.today().replace(day=1)
        income_mtd = sum(request.env['account.move'].sudo().search([
            ('move_type', '=', 'out_invoice'),
            ('payment_state', '=', 'paid'),
            ('invoice_date', '>=', month_start),
            ('invoice_date', '<=', date.today()),
            '|', '&', ('tenancy_property_id', 'in', property_ids),
                  ('tenancy_property_id', '!=', False),
                 '&', ('sold_property_id', 'in', property_ids),
                  ('sold_property_id', '!=', False),
        ]).mapped('amount_total'))

        return request.render(
            'sgc_offplan_rental_property_management.portal_landlord_portfolio', {
                'properties': properties,
                'property_count': len(properties),
                'occupancy': occupancy,
                'active_lease_count': rent_active + tenancy_active,
                'pending_maintenance': pending_maintenance,
                'income_mtd': income_mtd,
                'page_name': 'my_portfolio',
            }
        )

    # ── Landlord Properties ────────────────────────────────────────────────

    @http.route(['/my/portfolio/properties'], type='http', auth='user', website=True)
    def portal_landlord_properties(self, **kwargs):
        """List of properties owned by the landlord with occupancy info."""
        partner = request.env.user.partner_id
        properties = self._get_landlord_properties(partner)
        return request.render(
            'sgc_offplan_rental_property_management.portal_landlord_properties', {
                'properties': properties,
                'page_name': 'my_portfolio',
            }
        )

    # ── Landlord Tenants ───────────────────────────────────────────────────

    @http.route(['/my/portfolio/tenants'], type='http', auth='user', website=True)
    def portal_landlord_tenants(self, **kwargs):
        """Active tenants grouped by landlord's properties."""
        partner = request.env.user.partner_id
        property_ids = self._get_landlord_property_ids(partner)
        properties = request.env['property.details'].sudo().browse(property_ids)

        rent = request.env['rent.contract'].sudo().search([
            ('property_id', 'in', property_ids),
            ('state', '=', 'active'),
        ])
        tenancy = request.env['tenancy.details'].sudo().search([
            ('property_id', 'in', property_ids),
            ('state', '=', 'active'),
        ])

        tenants_by_property = {}
        for prop in properties:
            tenants_by_property[prop.id] = {'property': prop, 'leases': []}
        for lease in rent:
            tenants_by_property[lease.property_id.id]['leases'].append({
                'tenant': lease.tenant_id,
                'end_date': lease.end_date,
                'rent': lease.rent_amount,
                'model': 'rent_contract',
            })
        for lease in tenancy:
            tenants_by_property[lease.property_id.id]['leases'].append({
                'tenant': lease.tenant_id,
                'end_date': lease.end_date,
                'rent': lease.rent_amount,
                'model': 'tenancy_details',
            })

        grouped = [t for t in tenants_by_property.values() if t['leases']]

        return request.render(
            'sgc_offplan_rental_property_management.portal_landlord_tenants', {
                'grouped': grouped,
                'page_name': 'my_portfolio',
            }
        )

    # ── Landlord Income / Expenses ─────────────────────────────────────────

    @http.route(['/my/portfolio/income'], type='http', auth='user', website=True)
    def portal_landlord_income(self, date_from=None, date_to=None, **kwargs):
        """Income (paid invoices) and maintenance expenses for landlord."""
        partner = request.env.user.partner_id
        property_ids = self._get_landlord_property_ids(partner)

        today = date.today()
        default_from = (today - relativedelta(months=12)).replace(day=1)
        d_from = date_from or default_from.isoformat()
        d_to = date_to or today.isoformat()

        income_domain = [
            ('move_type', '=', 'out_invoice'),
            ('payment_state', '=', 'paid'),
            ('invoice_date', '>=', d_from),
            ('invoice_date', '<=', d_to),
        ]
        if property_ids:
            income_domain += ['|',
                '&', ('tenancy_property_id', 'in', property_ids),
                     ('tenancy_property_id', '!=', False),
                '&', ('sold_property_id', 'in', property_ids),
                     ('sold_property_id', '!=', False),
            ]
        else:
            income_domain += [('id', '=', False)]

        income_invoices = request.env['account.move'].sudo().search(
            income_domain, order='invoice_date desc')

        maintenance_ids = request.env['maintenance.request'].sudo().search([
            ('landlord_id', '=', partner.id),
        ]).ids
        expense_domain = [
            ('move_type', '=', 'in_invoice'),
            ('invoice_date', '>=', d_from),
            ('invoice_date', '<=', d_to),
        ]
        if maintenance_ids:
            expense_domain += [('maintenance_request_id', 'in', maintenance_ids)]
        else:
            expense_domain += [('id', '=', False)]
        expense_bills = request.env['account.move'].sudo().search(
            expense_domain, order='invoice_date desc')

        total_income = sum(income_invoices.mapped('amount_total'))
        total_expense = sum(expense_bills.mapped('amount_total'))
        net = total_income - total_expense

        return request.render(
            'sgc_offplan_rental_property_management.portal_landlord_income', {
                'income_invoices': income_invoices,
                'expense_bills': expense_bills,
                'total_income': total_income,
                'total_expense': total_expense,
                'net': net,
                'date_from': d_from,
                'date_to': d_to,
                'page_name': 'my_portfolio',
            }
        )

    # ── Landlord Statement ─────────────────────────────────────────────────

    @http.route(['/my/portfolio/statement'], type='http', auth='user', website=True)
    def portal_landlord_statement(self, date_from=None, date_to=None, **kwargs):
        """Owner-statement page mirroring the XLS wizard aggregation."""
        partner = request.env.user.partner_id
        property_ids = self._get_landlord_property_ids(partner)

        today = date.today()
        d_from = date_from or date(today.year, 1, 1).isoformat()
        d_to = date_to or today.isoformat()

        if property_ids:
            prop_domain = ['|',
                '&', ('tenancy_property_id', 'in', property_ids),
                     ('tenancy_property_id', '!=', False),
                '&', ('sold_property_id', 'in', property_ids),
                     ('sold_property_id', '!=', False),
            ]
        else:
            prop_domain = [('id', '=', False)]

        invoices = request.env['account.move'].sudo().search(
            [('move_type', '=', 'out_invoice'),
             ('invoice_date', '>=', d_from),
             ('invoice_date', '<=', d_to)] + prop_domain,
            order='invoice_date asc')

        tenancies = request.env['tenancy.details'].sudo().search([
            ('landlord_id', '=', partner.id),
        ])
        sales = request.env['property.vendor'].sudo().search([
            ('property_id.landlord_id', '=', partner.id),
        ])

        total_invoiced = sum(invoices.mapped('amount_total'))
        total_paid = sum(invoices.filtered(
            lambda i: i.payment_state == 'paid').mapped('amount_total'))
        total_outstanding = total_invoiced - total_paid

        return request.render(
            'sgc_offplan_rental_property_management.portal_landlord_statement', {
                'invoices': invoices,
                'tenancies': tenancies,
                'sales': sales,
                'total_invoiced': total_invoiced,
                'total_paid': total_paid,
                'total_outstanding': total_outstanding,
                'date_from': d_from,
                'date_to': d_to,
                'page_name': 'my_portfolio',
            }
        )

    @http.route(['/my/portfolio/statement/xls'], type='http', auth='user', website=True)
    def portal_landlord_statement_xls(self, date_from=None, date_to=None, **kwargs):
        """Stream an XLSX owner statement for the landlord's date range.

        The file is built in-process from the same aggregation the HTML
        statement page uses (out_invoices tied to the landlord's properties
        within the date range, plus invoiced/paid/outstanding totals) and the
        bytes are returned with spreadsheet download headers. The two legacy
        XLS wizards only return ``ir.actions.act_window_close`` and render no
        bytes, so the controller produces the workbook directly.
        """
        partner = request.env.user.partner_id
        property_ids = self._get_landlord_property_ids(partner)

        today = date.today()
        d_from = date_from or date(today.year, 1, 1).isoformat()
        d_to = date_to or today.isoformat()

        if property_ids:
            prop_domain = ['|',
                '&', ('tenancy_property_id', 'in', property_ids),
                     ('tenancy_property_id', '!=', False),
                '&', ('sold_property_id', 'in', property_ids),
                     ('sold_property_id', '!=', False),
            ]
        else:
            prop_domain = [('id', '=', False)]

        invoices = request.env['account.move'].sudo().search(
            [('move_type', '=', 'out_invoice'),
             ('invoice_date', '>=', d_from),
             ('invoice_date', '<=', d_to)] + prop_domain,
            order='invoice_date asc')

        total_invoiced = sum(invoices.mapped('amount_total'))
        total_paid = sum(invoices.filtered(
            lambda i: i.payment_state == 'paid').mapped('amount_total'))
        total_outstanding = total_invoiced - total_paid

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Owner Statement')

        title_fmt = workbook.add_format({'bold': True, 'font_size': 14})
        header_fmt = workbook.add_format(
            {'bold': True, 'bg_color': '#DDDDDD', 'border': 1})
        label_fmt = workbook.add_format({'bold': True})
        money_fmt = workbook.add_format({'num_format': '#,##0.00'})
        total_fmt = workbook.add_format({'bold': True, 'num_format': '#,##0.00'})

        sheet.set_column(0, 0, 22)
        sheet.set_column(1, 1, 16)
        sheet.set_column(2, 2, 30)
        sheet.set_column(3, 3, 16)
        sheet.set_column(4, 4, 18)

        sheet.write(0, 0, 'Owner Statement', title_fmt)
        sheet.write(1, 0, 'Period', label_fmt)
        sheet.write(1, 1, '%s to %s' % (d_from, d_to))

        sheet.write(3, 0, 'Total Invoiced', label_fmt)
        sheet.write(3, 1, total_invoiced, money_fmt)
        sheet.write(4, 0, 'Total Paid', label_fmt)
        sheet.write(4, 1, total_paid, money_fmt)
        sheet.write(5, 0, 'Total Outstanding', label_fmt)
        sheet.write(5, 1, total_outstanding, money_fmt)

        header_row = 7
        for col, col_label in enumerate(
                ['Invoice', 'Date', 'Customer', 'Amount', 'Payment Status']):
            sheet.write(header_row, col, col_label, header_fmt)

        row = header_row + 1
        for inv in invoices:
            sheet.write(row, 0, inv.name or '')
            sheet.write(
                row, 1, inv.invoice_date.isoformat() if inv.invoice_date else '')
            sheet.write(row, 2, inv.partner_id.name or '')
            sheet.write(row, 3, inv.amount_total, money_fmt)
            sheet.write(row, 4, inv.payment_state or '')
            row += 1

        sheet.write(row, 2, 'Total', label_fmt)
        sheet.write(row, 3, total_invoiced, total_fmt)

        workbook.close()
        output.seek(0)
        xlsx_data = output.read()

        filename = 'owner_statement_%s_%s.xlsx' % (d_from, d_to)
        return request.make_response(
            xlsx_data,
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename="%s"' % filename),
                ('Content-Length', str(len(xlsx_data))),
            ],
        )

    # ── Landlord Maintenance ───────────────────────────────────────────────

    @http.route(['/my/portfolio/maintenance'], type='http', auth='user', website=True)
    def portal_landlord_maintenance(self, **kwargs):
        """Maintenance approval queue scoped to the landlord."""
        partner = request.env.user.partner_id
        maintenance = request.env['maintenance.request'].sudo().search([
            ('landlord_id', '=', partner.id),
        ])
        pending = maintenance.filtered(
            lambda m: m.landlord_approval_state == 'pending')
        other = maintenance.filtered(
            lambda m: m.landlord_approval_state != 'pending')
        ordered = pending + other
        approval_states = \
            request.env['maintenance.request']._fields['landlord_approval_state'].selection
        return request.render(
            'sgc_offplan_rental_property_management.portal_landlord_maintenance', {
                'maintenance_requests': ordered,
                'approval_states': approval_states,
                'page_name': 'my_portfolio',
            }
        )

    @http.route([
        '/my/portfolio/maintenance/<int:maintenance_id>/approve',
    ], type='http', auth='user', website=True, methods=['POST'])
    def portal_landlord_maintenance_approve(self, maintenance_id, **kwargs):
        """Approve a maintenance request as the owning landlord."""
        partner = request.env.user.partner_id
        maintenance = request.env['maintenance.request'].sudo().browse(maintenance_id)
        if not maintenance.exists() or maintenance.landlord_id.id != partner.id:
            return request.render('website.page_404')
        maintenance.action_landlord_approve()
        return request.redirect('/my/portfolio/maintenance')

    @http.route([
        '/my/portfolio/maintenance/<int:maintenance_id>/reject',
    ], type='http', auth='user', website=True, methods=['POST'])
    def portal_landlord_maintenance_reject(self, maintenance_id, **kwargs):
        """Reject a maintenance request as the owning landlord."""
        partner = request.env.user.partner_id
        maintenance = request.env['maintenance.request'].sudo().browse(maintenance_id)
        if not maintenance.exists() or maintenance.landlord_id.id != partner.id:
            return request.render('website.page_404')
        reason = kwargs.get('reason') or None
        maintenance.action_landlord_reject(reason=reason)
        return request.redirect('/my/portfolio/maintenance')

    # ── Landlord Documents ─────────────────────────────────────────────────

    @http.route(['/my/portfolio/documents'], type='http', auth='user', website=True)
    def portal_landlord_documents(self, **kwargs):
        """Portal-visible documents for the landlord's properties (read-only)."""
        partner = request.env.user.partner_id
        property_ids = self._get_landlord_property_ids(partner)
        documents = request.env['property.documents'].sudo().search([
            ('portal_visible', '=', True),
            ('property_id', 'in', property_ids),
        ])
        properties = self._get_landlord_properties(partner)
        doc_categories = \
            request.env['property.documents']._fields['doc_category'].selection
        return request.render(
            'sgc_offplan_rental_property_management.portal_landlord_documents', {
                'documents': documents,
                'properties': properties,
                'doc_categories': doc_categories,
                'page_name': 'my_portfolio',
            }
        )

    # ── Customer helpers ───────────────────────────────────────────────────

    def _customer_partner(self):
        """Return request.env.user.partner_id (sugar)."""
        return request.env.user.partner_id

    def _safe_redirect_referrer(self, default):
        """Return request.httprequest.referrer if it points to this host, else default."""
        referrer = request.httprequest.referrer
        host = request.httprequest.host_url
        if referrer and host and referrer.startswith(host):
            return referrer
        return default

    def _customer_active_property_ids(self, partner):
        """Return property ids already locked in an active sale.contract or property.vendor."""
        sale_ids = request.env['sale.contract'].sudo().search([
            ('buyer_id', '=', partner.id),
            ('state', 'not in', ['cancelled']),
        ]).mapped('property_id').ids
        vendor_ids = request.env['property.vendor'].sudo().search([
            ('customer_id', '=', partner.id),
            ('state', 'not in', ['cancelled']),
        ]).mapped('property_id').ids
        return set(sale_ids) | set(vendor_ids)

    # ── Customer Favorites ─────────────────────────────────────────────────

    @http.route(['/my/favorites'], type='http', auth='user', website=True)
    def portal_customer_favorites(self, **kwargs):
        """List customer's favorite properties."""
        partner = self._customer_partner()
        favorites = request.env['property.details'].sudo().search([
            ('id', 'in', partner.favorite_property_ids.ids),
            ('is_published_website', '=', True),
        ])
        return request.render(
            'sgc_offplan_rental_property_management.portal_customer_favorites', {
                'favorites': favorites,
                'page_name': 'my_favorites',
            }
        )

    @http.route([
        '/my/favorites/<int:property_id>/add',
    ], type='http', auth='user', website=True, methods=['POST'])
    def portal_customer_favorites_add(self, property_id, **kwargs):
        """Add a portal-published property to the customer's favorites."""
        partner = self._customer_partner()
        property = request.env['property.details'].sudo().browse(property_id)
        if not property.exists() or not property.is_published_website:
            return request.render('website.page_404')
        if property_id not in partner.favorite_property_ids.ids:
            partner.write({'favorite_property_ids': [
                (4, property_id),
            ]})
        return request.redirect(
            self._safe_redirect_referrer('/my/favorites'))

    @http.route([
        '/my/favorites/<int:property_id>/remove',
    ], type='http', auth='user', website=True, methods=['POST'])
    def portal_customer_favorites_remove(self, property_id, **kwargs):
        """Remove a property from the customer's favorites."""
        partner = self._customer_partner()
        if property_id in partner.favorite_property_ids.ids:
            partner.write({'favorite_property_ids': [
                (3, property_id),
            ]})
        return request.redirect(
            self._safe_redirect_referrer('/my/favorites'))

    # ── Customer Inquiries ─────────────────────────────────────────────────

    @http.route(['/my/inquiries/new'], type='http', auth='user', website=True)
    def portal_customer_inquiry_new(self, **kwargs):
        """Booking/quotation inquiry form."""
        partner = self._customer_partner()
        locked_ids = self._customer_active_property_ids(partner)
        domain = [('is_published_website', '=', True)]
        if locked_ids:
            domain += [('id', 'not in', list(locked_ids))]
        properties = request.env['property.details'].sudo().search(domain, limit=100)
        return request.render(
            'sgc_offplan_rental_property_management.portal_customer_inquiry_new', {
                'properties': properties,
                'partner': partner,
                'error': kwargs.get('error'),
                'page_name': 'my_inquiries',
            }
        )

    @http.route(['/my/inquiries/new'], type='http', auth='user', website=True,
                methods=['POST'])
    def portal_customer_inquiry_submit(self, **kwargs):
        """Submit a new inquiry as a CRM lead for the customer."""
        partner = self._customer_partner()
        try:
            property_id = int(kwargs.get('property_id', 0)) if kwargs.get('property_id') else 0
        except (TypeError, ValueError):
            property_id = 0
        notes = kwargs.get('notes') or ''
        proposed_price_raw = kwargs.get('proposed_price')
        contact_phone = kwargs.get('contact_phone') or partner.phone or ''
        property = request.env['property.details'].sudo().browse(property_id) if property_id else False
        if not property or not property.exists() or not property.is_published_website:
            return request.redirect('/my/inquiries/new')
        locked_ids = self._customer_active_property_ids(partner)
        if property_id in locked_ids:
            return request.redirect('/my/inquiries/new')
        try:
            expected_revenue = float(proposed_price_raw) if proposed_price_raw else 0.0
        except (TypeError, ValueError):
            expected_revenue = 0.0
        try:
            lead = request.env['crm.lead'].sudo().create({
                'name': 'Portal Inquiry: %s' % (property.name or ''),
                'partner_id': partner.id,
                'property_id': property.id,
                'description': notes,
                'expected_revenue': expected_revenue,
                'phone': contact_phone,
                'email_from': partner.email or False,
                'type': 'opportunity',
            })
            if notes:
                lead.message_post(
                    body=_('Inquiry submitted via portal by %s.') % partner.name,
                    message_type='comment',
                    subtype_xmlid='mail.mt_note')
            return request.redirect('/my/inquiries')
        except Exception as e:
            _logger.error("Inquiry submit error: %s", str(e), exc_info=True)
            return request.redirect('/my/inquiries/new?error=1')

    @http.route(['/my/inquiries'], type='http', auth='user', website=True)
    def portal_customer_inquiries(self, **kwargs):
        """List customer's inquiries (CRM leads linked to portal customer)."""
        partner = self._customer_partner()
        leads = request.env['crm.lead'].sudo().search([
            ('partner_id', '=', partner.id),
            ('property_id', '!=', False),
        ], order='create_date desc')
        return request.render(
            'sgc_offplan_rental_property_management.portal_customer_inquiries', {
                'inquiries': leads,
                'page_name': 'my_inquiries',
            }
        )

    @http.route(['/my/inquiries/<int:inquiry_id>'], type='http', auth='user', website=True)
    def portal_customer_inquiry_detail(self, inquiry_id, **kwargs):
        """Detail view for a single inquiry."""
        partner = self._customer_partner()
        lead = request.env['crm.lead'].sudo().browse(inquiry_id)
        if not lead.exists() or lead.partner_id.id != partner.id:
            return request.render('website.page_404')
        return request.render(
            'sgc_offplan_rental_property_management.portal_customer_inquiry_detail', {
                'inquiry': lead,
                'page_name': 'my_inquiries',
            }
        )

    # ── Customer Purchases (sale.contract history) ─────────────────────────

    @http.route(['/my/purchases'], type='http', auth='user', website=True)
    def portal_customer_purchases(self, **kwargs):
        """Customer purchase history (sale.contracts where buyer = current customer)."""
        partner = self._customer_partner()
        purchases = request.env['sale.contract'].sudo().search([
            ('buyer_id', '=', partner.id),
        ], order='contract_date desc, id desc')
        return request.render(
            'sgc_offplan_rental_property_management.portal_customer_purchases', {
                'purchases': purchases,
                'page_name': 'my_purchases',
            }
        )

    # ── Customer Bookings (property.vendor reservations) ────────────────────

    @http.route(['/my/bookings'], type='http', auth='user', website=True)
    def portal_customer_bookings(self, **kwargs):
        """Customer reservation tracking (property.vendor where customer = current partner)."""
        partner = self._customer_partner()
        bookings = request.env['property.vendor'].sudo().search([
            ('customer_id', '=', partner.id),
        ], order='date desc, id desc')
        return request.render(
            'sgc_offplan_rental_property_management.portal_customer_bookings', {
                'bookings': bookings,
                'page_name': 'my_bookings',
            }
        )

    @http.route([
        '/my/bookings/<int:booking_id>/cancel',
    ], type='http', auth='user', website=True, methods=['POST'])
    def portal_customer_booking_cancel(self, booking_id, **kwargs):
        """Cancel a draft booking. Returns 404 if past draft state."""
        partner = self._customer_partner()
        booking = request.env['property.vendor'].sudo().browse(booking_id)
        if not booking.exists() or booking.customer_id.id != partner.id:
            return request.render('website.page_404')
        valid_states = {'draft'}
        state_field = request.env['property.vendor']._fields.get('state')
        allowed_states = set(state_field.selection or []) if state_field else set()
        if 'cancelled' not in allowed_states:
            _logger.warning(
                "property.vendor does not support 'cancelled' state; cannot cancel booking %s.",
                booking_id)
            return request.render('website.page_404')
        if booking.state not in valid_states:
            return request.render('website.page_404')
        booking.write({'state': 'cancelled'})
        return request.redirect('/my/bookings')

    # ── Customer E-Signature (MVP seam for Phase 4 integration) ────────────

    @http.route([
        '/my/contracts/<int:contract_id>/sign',
    ], type='http', auth='user', website=True)
    def portal_customer_contract_sign(self, contract_id, **kwargs):
        """Render a confirmation page for portal-based e-signature.

        MVP: no cryptography. The 'I agree & sign' button sets
        ``signed_via_portal`` and posts a chatter note. Phase 4 will replace
        this with a real e-sign provider (e.g. DocuSign or OCA ``sign``).
        """
        partner = self._customer_partner()
        contract = request.env['sale.contract'].sudo().browse(contract_id)
        if not contract.exists() or contract.buyer_id.id != partner.id:
            return request.render('website.page_404')
        return request.render(
            'sgc_offplan_rental_property_management.portal_customer_sign_contract', {
                'contract': contract,
                'page_name': 'my_contracts',
            }
        )

    @http.route([
        '/my/contracts/<int:contract_id>/sign',
    ], type='http', auth='user', website=True, methods=['POST'])
    def portal_customer_contract_sign_submit(self, contract_id, **kwargs):
        """Set signed_via_portal=True and post a chatter note."""
        partner = self._customer_partner()
        contract = request.env['sale.contract'].sudo().browse(contract_id)
        if not contract.exists() or contract.buyer_id.id != partner.id:
            return request.render('website.page_404')
        contract.write({'signed_via_portal': True})
        contract.message_post(
            body=_('Customer %s acknowledged the contract via the portal (MVP e-sign seam).')
                % partner.name,
            message_type='comment',
            subtype_xmlid='mail.mt_note')
        return request.redirect('/my/contract/sale/%s' % contract_id)
