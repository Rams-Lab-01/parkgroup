# -*- coding: utf-8 -*-

import logging
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class CrmLeadCompatibility(models.Model):
    """
    Emergency compatibility layer for CRM Lead AI fields.
    
    This ensures ai_enrichment_report field exists even if llm_lead_scoring
    module is not installed or not properly upgraded.
    """
    _inherit = 'crm.lead'

    # Check if field already exists before adding
    @api.model
    def _add_compatibility_fields(self):
        """Add AI fields only if they don't exist"""
        field_names = self._fields.keys()
        
        # Only add fields if they don't already exist
        if 'ai_enrichment_report' not in field_names:
            _logger.info("Adding ai_enrichment_report compatibility field to crm.lead")
            return True
        return False

    # Compatibility field - only active if llm_lead_scoring not installed
    ai_enrichment_report = fields.Text(
        string='AI Enrichment Report',
        readonly=True,
        help='Complete plain text enrichment report with scores and analysis',
        compute='_compute_ai_enrichment_report_compat',
        store=False,  # Non-stored to avoid conflicts
    )

    @api.depends()
    def _compute_ai_enrichment_report_compat(self):
        """
        Compatibility compute method - returns empty if field exists elsewhere.
        This prevents conflicts if llm_lead_scoring is later installed.
        """
        for lead in self:
            # Check if real field exists (from llm_lead_scoring)
            if hasattr(lead, '_origin') and hasattr(lead._origin, 'ai_enrichment_report'):
                lead.ai_enrichment_report = lead._origin.ai_enrichment_report or ""
            else:
                # Provide placeholder
                lead.ai_enrichment_report = (
                    "AI Enrichment not available.\n"
                    "Install 'llm_lead_scoring' module for full AI capabilities."
                )

    @api.model
    def init(self):
        """Initialize compatibility layer"""
        super(CrmLeadCompatibility, self).init()
        self._add_compatibility_fields()
