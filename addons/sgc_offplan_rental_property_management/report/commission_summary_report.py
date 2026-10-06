# -*- coding: utf-8 -*-
# Copyright 2026 SGC TECH AI
# Part of SGC Odoo Suite. See LICENSE file for full copyright and licensing details.

from odoo import api, models


class CommissionSummaryReport(models.AbstractModel):
    """Normalise sale/rent/vendor commission data for the shared QWeb body.

    Odoo picks the custom report model with ``'report.' + action.report_name``
    (see ``ir.actions.report._get_rendering_context_model``).  One
    ``report_name`` shared by three actions therefore resolved to a single
    report model for all three, and the class could only guess the source model
    from a hard-coded template external id: that guess broke as soon as the
    template was renamed and could not tell a sale contract from a rent
    contract or a vendor record in any case.

    Each action now has its own thin template and its own report model, and the
    source model is declared on the subclass.  ``docs`` is the plain recordset:
    the QWeb body renders each record directly (``o.name``,
    ``o.commission_line_ids``, ``'commission_amount_total' in o._fields``), so a
    normalised mapping would not fit it.

    ``_table`` is set explicitly on every class: Odoo derives and validates a
    table name from the model name even for report models that never own a
    table, and the derived name for these model names exceeds the 63 character
    PostgreSQL identifier limit (Entry 24).
    """

    _name = "report.sgc_offplan_rental_property_management.commission_summary.base"
    _table = "cs_summary_report_base"
    _description = "Commission Summary Report - base normaliser"

    _target_model = "sale.contract"

    @api.model
    def _get_report_values(self, docids, data=None):
        model = self._target_model
        return {
            "doc_ids": docids,
            "doc_model": model,
            "docs": self.env[model].browse(docids),
        }


class CommissionSummarySaleReport(models.AbstractModel):
    _name = "report.sgc_offplan_rental_property_management.commission_summary_sale"
    _table = "cs_summary_report_sale"
    _inherit = "report.sgc_offplan_rental_property_management.commission_summary.base"
    _description = "Commission Summary Report (Sale)"
    _target_model = "sale.contract"


class CommissionSummaryRentReport(models.AbstractModel):
    _name = "report.sgc_offplan_rental_property_management.commission_summary_rent"
    _table = "cs_summary_report_rent"
    _inherit = "report.sgc_offplan_rental_property_management.commission_summary.base"
    _description = "Commission Summary Report (Rent)"
    _target_model = "rent.contract"


class CommissionSummaryVendorReport(models.AbstractModel):
    _name = "report.sgc_offplan_rental_property_management.commission_summary_vendor"
    _table = "cs_summary_report_vendor"
    _inherit = "report.sgc_offplan_rental_property_management.commission_summary.base"
    _description = "Commission Summary Report (Vendor)"
    _target_model = "property.vendor"


class CommissionSummaryLegacyReport(models.AbstractModel):
    """Legacy shared ``report_name`` kept so an action that still points at
    ``commission_summary`` renders instead of falling back to generic values."""

    _name = "report.sgc_offplan_rental_property_management.commission_summary"
    _table = "commission_summary"
    _inherit = "report.sgc_offplan_rental_property_management.commission_summary.base"
    _description = "Commission Summary Report (legacy shared name)"
    _target_model = "sale.contract"
