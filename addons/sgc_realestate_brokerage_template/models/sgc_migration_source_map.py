# -*- coding: utf-8 -*-
# Part of SGC Realestate Brokerage Template (reconciled build, 2026-08-31).
#
# Brief §2.12 — answers "where master data currently lives for
# contacts / properties / contracts / documents." Captures the
# per-source-table → per-target-model mapping rule for Phase 1.
#
# Constraint #4 model name: `sgc.migration.source_map`.
from odoo import _, api, fields, models


class SgcMigrationSourceMap(models.Model):
    _name = "sgc.migration.source_map"
    _description = "Per-source-table to per-target-model migration rule"
    _order = "sequence, source_table"
    _rec_name = "source_table"

    tenant_id = fields.Many2one(
        "sgc.brokerage.tenant", required=True, check_company=True,
    )
    integration_source_id = fields.Many2one(
        "sgc.integration.source",
        required=True,
        domain="[('tenant_id', '=', tenant_id)]",
        help="Foreign key to the external system declared in "
             "`sgc.integration.source`.",
    )
    sequence = fields.Integer(default=10)
    source_table = fields.Char(
        required=True, index=True,
        help="Source-side table or entity name. e.g. 'contacts', "
             "'listings', 'leases_v2'.",
    )
    target_model = fields.Char(
        required=True,
        help="Target Odoo model — typically `res.partner`, `re.unit`, "
             "`sale.order`, `tenancy.details`, etc.",
    )
    mapping_rule = fields.Text(
        required=True,
        help="Free-text description of the field-by-field mapping rule. "
             "Multi-line. Engineered to be readable by both engineers "
             "and operations staff during Phase 1 sign-off.",
    )
    estimated_row_count = fields.Integer(
        help="Pre-migration estimate. Updated after the first dry-run.",
    )
    last_run_id = fields.Many2one(
        "sgc.migration.run",
        help="Pointer to the most-recent `sgc.migration.run` for this map.",
    )

    _sgc_migration_source_map_unique = models.Constraint(
        "unique(tenant_id, integration_source_id, source_table)",
        "Each (tenant, source-system, source-table) row is unique — "
        "if you need to remap a table, supersede the existing rule "
        "rather than adding a row.",
    )


class SgcMigrationRun(models.Model):
    """Sibling model recording the actual outcome of each migration run.
    The brief did not list this name explicitly but the source-map
    model needs a `last_run_id` reference; it is the same logical
    unit and was already named in the data-extraction report.
    """

    _name = "sgc.migration.run"
    _description = "Recorded outcome of a source-map migration run"
    _order = "started_at desc"

    tenant_id = fields.Many2one(
        "sgc.brokerage.tenant", required=True, check_company=True,
    )
    integration_source_id = fields.Many2one(
        "sgc.integration.source", required=True,
    )
    started_at = fields.Datetime(required=True, default=fields.Datetime.now)
    finished_at = fields.Datetime(readonly=True)
    total_count = fields.Integer()
    success_count = fields.Integer()
    fail_count = fields.Integer()
    log_ids = fields.One2many(
        "sgc.migration.run.log",
        "run_id",
        string="Per-row outcome log",
    )


class SgcMigrationRunLog(models.Model):
    _name = "sgc.migration.run.log"
    _description = "Per-row outcome of a migration run"
    _order = "run_id, sequence"

    run_id = fields.Many2one(
        "sgc.migration.run", required=True, ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    source_pk = fields.Char(
        help="Source-system primary key for this row.",
    )
    outcome = fields.Selection(
        selection=[
            ("created", "Created"),
            ("updated", "Updated"),
            ("skipped", "Skipped (already-present)"),
            ("failed", "Failed"),
        ],
        required=True,
    )
    failure_message = fields.Text()
