# -*- coding: utf-8 -*-
# Copyright 2025 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.
import base64
import io
import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

# Report names whose rendered PDF should carry the property floor plan when the
# floor plan is a PDF (image floor plans are embedded inline by the QWeb
# templates themselves).
PM_FLOOR_PLAN_REPORTS = (
    'sgc_offplan_rental_property_management.sales_offer_template',
    'sgc_offplan_rental_property_management.sales_offer_property_template',
    'sgc_offplan_rental_property_management.sales_purchase_agreement_template',
    'sgc_offplan_rental_property_management.sales_purchase_agreement_contract_template',
)


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        """Append PDF floor plans to property-facing PDF reports.

        wkhtmltopdf renders base64 data-URI <img> elements, so image floor
        plans are embedded inline by the QWeb templates. PDF floor plans cannot
        be painted by wkhtmltopdf, so after each per-record stream of a Sales
        Offer / Property Offer Sheet / Sales Purchase Agreement is rendered the
        property's floor-plan PDF is merged onto the end of that stream here
        (via Odoo's own _merge_pdfs), so it travels with the document as
        trailing pages. Multi-record merges still interleave correctly because
        every record's stream is extended before Odoo merges them together.
        """
        collected_streams = super()._render_qweb_pdf_prepare_streams(
            report_ref, data, res_ids=res_ids)
        try:
            report = self._get_report(report_ref)
        except Exception:
            return collected_streams
        if (not report or report.report_name not in PM_FLOOR_PLAN_REPORTS
                or report.model not in ('property.vendor', 'property.details', 'sale.contract')):
            return collected_streams
        model = self.env[report.model]
        for res_id, out in (collected_streams or {}).items():
            stream = (out or {}).get('stream')
            if not stream:
                continue
            record = model.browse(res_id)
            prop = self._pm_report_offer_property(record)
            if not prop:
                continue
            floor_plan = prop._report_floor_plan_data()
            if floor_plan.get('kind') != 'pdf' or not floor_plan.get('pdf_b64'):
                continue
            try:
                floor_stream = io.BytesIO(base64.b64decode(floor_plan['pdf_b64']))

                def _on_merge_error(error, error_stream):
                    _logger.warning(
                        "Floor plan could not be appended to %s report of record %s: %s",
                        report.report_name, res_id, error)

                # _merge_pdfs returns a BytesIO used here as a context manager
                # which CLOSES the stream on exit - so capture the payload while
                # the stream is open and hand back a fresh open BytesIO.
                with self._merge_pdfs([stream, floor_stream], handle_error=_on_merge_error) as merged:
                    merged.seek(0)
                    out['stream'] = io.BytesIO(merged.read())
            except Exception:
                _logger.exception(
                    "Failed to append floor-plan PDF to %s report of record %s",
                    report.report_name, res_id)
        return collected_streams

    @api.model
    def _pm_report_offer_property(self, record):
        """Resolve the property.details record a reporting record refers to."""
        if not record:
            return self.env['property.details']
        if record._name == 'property.details':
            return record
        if record._name == 'property.vendor':
            if record.property_id:
                return record.property_id
            return record.sale_contract_id.property_id if record.sale_contract_id \
                else self.env['property.details']
        if record._name == 'sale.contract':
            return record.property_id
        return self.env['property.details']