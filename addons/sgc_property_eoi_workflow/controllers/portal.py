# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
"""Portal digital signature for the SPA, mirroring the sale.order quotation flow.

Access is guarded by the one-time ``spa_access_token`` (emailed with the SPA)
or by the buyer/joint-buyer ownership check, mirroring the "Portal: Own Purchase"
record rule on ``sale.contract``.
"""

import binascii

from odoo import http, _
from odoo.exceptions import UserError
from odoo.http import request


class ContractSpaSignaturePortal(http.Controller):

    def _get_contract(self, contract_id, token=None):
        contract = request.env['sale.contract'].sudo().browse(int(contract_id))
        if not contract.exists():
            return None
        if token and contract.spa_access_token and token == contract.spa_access_token:
            return contract
        partner = request.env.user.partner_id
        allowed = {contract.buyer_id.id, contract.joint_buyer_id.id}
        allowed.discard(False)
        if partner.id in allowed:
            return contract
        return None

    def _render_spa_pdf(self, contract):
        pdf_content, _report_type = request.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'sgc_offplan_rental_property_management.action_report_sales_purchase_agreement_contract',
            res_ids=contract.ids,
        )
        return pdf_content

    @http.route('/my/contract/sale/<int:contract_id>/spa/sign',
                type='http', auth='public', website=True, methods=['GET'])
    def spa_sign(self, contract_id, **post):
        contract = self._get_contract(contract_id, post.get('token'))
        if not contract or contract.state not in ('spa_issued', 'spa_signed'):
            return request.not_found()
        return request.render('sgc_property_eoi_workflow.portal_spa_sign', {
            'contract': contract,
            'signed_ok': post.get('message') == 'sign_ok',
        })

    @http.route('/my/contract/sale/<int:contract_id>/spa/accept',
                type='jsonrpc', auth='public', website=True)
    def spa_accept(self, contract_id, access_token=None, token=None, name=None, signature=None):
        """Quotation-style e-signature: record signature, SPA Issued -> SPA Signed."""
        token = token or access_token or request.httprequest.args.get('token')
        contract = self._get_contract(contract_id, token)
        if not contract:
            return {'error': _('This signature link is invalid or has expired.')}
        if not contract._spa_has_to_be_signed():
            return {'error': _('This agreement is not awaiting your signature.')}
        if not signature:
            return {'error': _('Signature is missing.')}
        try:
            contract.spa_sign_from_portal(name, signature)
            # flush now so the signature is available to the PDF render
            request.env.cr.flush()
        except UserError as error:
            return {'error': str(error)}
        except (TypeError, binascii.Error):
            return {'error': _('Invalid signature data.')}
        params = ['message=sign_ok']
        if contract.spa_access_token:
            params.insert(0, 'token=%s' % contract.spa_access_token)
        return {
            'force_refresh': True,
            'redirect_url': '/my/contract/sale/%s/spa/sign?%s' % (contract.id, '&'.join(params)),
        }

    @http.route('/my/contract/sale/<int:contract_id>/spa/pdf',
                type='http', auth='public', website=True)
    def spa_pdf(self, contract_id, **kw):
        contract = self._get_contract(contract_id, kw.get('token'))
        if not contract or contract.state not in ('spa_issued', 'spa_signed'):
            return request.not_found()
        pdf = self._render_spa_pdf(contract)
        filename = 'SPA-%s%s.pdf' % (
            contract.name.replace('/', '-'),
            '-Signed' if contract.state == 'spa_signed' else '')
        return request.make_response(pdf, headers=[
            ('Content-Type', 'application/pdf'),
            ('Content-Disposition', http.content_disposition(filename)),
        ])
