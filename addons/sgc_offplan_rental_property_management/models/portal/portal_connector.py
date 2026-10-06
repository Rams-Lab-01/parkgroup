# -*- coding: utf-8 -*-
import logging
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from . import inbound_feed_service
from . import rapidapi_market_data_service

_logger = logging.getLogger(__name__)


class PortalConnector(models.Model):
    _name = "portal.connector"
    _description = "Property Portal Connector"
    _inherit = ["mail.thread", "mail.activity.mixin", "sgc.critical.audit.mixin"]

    name = fields.Char(required=True, tracking=True)
    code = fields.Selection(
        [
            ("bayut", "Bayut"),
            ("dubizzle", "Dubizzle"),
            ("property_finder", "Property Finder"),
            ("houza", "Houza"),
            ("property_monitor", "Property Monitor"),
            ("custom", "Custom Portal"),
        ],
        required=True,
        tracking=True,
    )
    active = fields.Boolean(default=True, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    sync_frequency = fields.Selection(
        [
            ("realtime", "Real-time"),
            ("15min", "Every 15 Minutes"),
            ("30min", "Every 30 Minutes"),
            ("hourly", "Hourly"),
            ("daily", "Daily"),
            ("manual", "Manual Only"),
        ],
        default="manual",
        required=True,
        tracking=True,
    )
    xml_feed_token = fields.Char(
        default=lambda self: secrets.token_urlsafe(32),
        copy=False,
        tracking=False,  # SECURITY: Never track tokens in chatter
        groups="sgc_offplan_rental_property_management.group_portal_admin",
        help="Security token required to access the XML feed. Keep this confidential.",
    )
    token_last_used = fields.Datetime(readonly=True, help="Last time the feed was accessed")
    token_usage_count = fields.Integer(readonly=True, default=0, help="Number of times feed accessed")
    xml_feed_url = fields.Char(
        compute="_compute_xml_feed_url",
        store=True,
        groups="sgc_offplan_rental_property_management.group_portal_admin",
        help="Contains the feed token in the query string. Keep this confidential.",
    )

    api_key = fields.Char(
        groups="sgc_offplan_rental_property_management.group_portal_admin",
        help="RapidAPI key (x-rapidapi-key) used by the 'Test RapidAPI Connection' button.",
    )
    api_secret = fields.Char(groups="sgc_offplan_rental_property_management.group_portal_admin")

    webhook_secret = fields.Char(
        default=lambda self: secrets.token_urlsafe(32),
        copy=False,
        tracking=False,  # SECURITY: Never track secrets in chatter
        groups="sgc_offplan_rental_property_management.group_portal_admin",
        help="Shared secret used to verify the HMAC-SHA256 X-Signature header on inbound "
             "/portal-webhook/<code> requests. Only enforced once the webhook kill-switch "
             "(ir.config_parameter 'sgc_offplan_rental_property_management.portal_webhook_enabled') "
             "is turned on.",
    )
    api_endpoint = fields.Char(
        help="RapidAPI host (x-rapidapi-host), e.g. uae-real-estate3.p.rapidapi.com. "
             "Leave blank to use the default host for this portal's code.",
    )

    # Inbound feed configuration
    inbound_feed_url = fields.Char(
        string="Inbound Feed URL",
        groups="sgc_offplan_rental_property_management.group_portal_admin",
        help="URL to fetch XML feed from this portal (for Bayut/Dubizzle property imports)"
    )
    inbound_feed_username = fields.Char(
        string="Inbound Feed Username",
        groups="sgc_offplan_rental_property_management.group_portal_admin",
        help="Username for inbound feed authentication (if required)"
    )
    inbound_feed_password = fields.Char(
        string="Inbound Feed Password",
        groups="sgc_offplan_rental_property_management.group_portal_admin",
        help="Password for inbound feed authentication (if required)"
    )

    last_sync_date = fields.Datetime(readonly=True, tracking=True)
    last_sync_status = fields.Selection(
        [
            ("success", "Success"),
            ("partial", "Partial Success"),
            ("failed", "Failed"),
            ("pending", "Pending"),
        ],
        readonly=True,
    )
    last_sync_message = fields.Text(readonly=True)

    listing_line_ids = fields.One2many(
        "property.portal.line",
        "portal_id",
        string="Listings",
    )
    log_ids = fields.One2many(
        "portal.sync.log",
        "portal_id",
        string="Sync Logs",
    )

    _check_connector_unique = models.Constraint(
        'unique(code, company_id)',
        'Connector per portal per company must be unique.',
    )

    @api.depends("xml_feed_token", "code", "company_id")
    def _compute_xml_feed_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url", default="")
        for record in self:
            if base_url and record.xml_feed_token:
                record.xml_feed_url = "%s/portal-feed/%s?token=%s" % (
                    base_url.rstrip("/"), record.code or "custom", record.xml_feed_token
                )
            else:
                record.xml_feed_url = False

    @api.constrains("xml_feed_token")
    def _check_token_length(self):
        for record in self:
            if record.xml_feed_token and len(record.xml_feed_token) < 16:
                raise ValidationError(_("Feed token is too short."))

    @api.model
    def process_inbound_feeds(self):
        """Process inbound feeds for all portals that have an inbound_feed_url.

        Called by the scheduled cron job (ir_cron_process_all_inbound_feeds
        in data/ir_cron_feed_ingest.xml). Delegates the actual fetch + parse
        + record-creation work to inbound_feed_service so the controller and
        cron share the same code path.
        """
        _logger.info("Starting inbound feed processing cron job")

        env = self.env
        portals_with_feeds = self.sudo().search([
            ("inbound_feed_url", "!=", False),
            ("active", "=", True),
        ])

        _logger.info(
            "Found %d portals with inbound feeds configured",
            len(portals_with_feeds),
        )

        total_created = 0
        total_updated = 0
        total_errors = 0

        for portal in portals_with_feeds:
            try:
                _logger.info(
                    "Processing inbound feed for portal: %s (%s)",
                    portal.name, portal.code,
                )

                feed_xml = inbound_feed_service.fetch_feed_xml(
                    env,
                    portal.inbound_feed_url,
                    portal.inbound_feed_username,
                    portal.inbound_feed_password,
                )
                created, updated, errors = (
                    inbound_feed_service.process_feed_properties(
                        env, portal, feed_xml,
                    )
                )

                total_created += created
                total_updated += updated
                total_errors += len(errors)

                portal.sudo().write({
                    "last_sync_date": fields.Datetime.now(),
                    "last_sync_status": (
                        "success" if not errors else "partial"
                    ),
                    "last_sync_message": (
                        "Processed {} new, {} updated properties. "
                        "{} errors.".format(
                            created, updated, len(errors),
                        )
                    ),
                })
                env["portal.sync.log"].sudo().create({
                    "portal_id": portal.id,
                    "status": "success" if not errors else "partial",
                    "created_count": created,
                    "updated_count": updated,
                    "failed_count": len(errors),
                    "message": (
                        "Cron feed ingest: {} new, {} updated, "
                        "{} errors".format(
                            created, updated, len(errors),
                        )
                    ),
                })
            except Exception as e:  # noqa: BLE001
                _logger.exception(
                    "Error processing feed for portal %s: %s",
                    portal.code, e,
                )
                portal.sudo().write({
                    "last_sync_date": fields.Datetime.now(),
                    "last_sync_status": "failed",
                    "last_sync_message": "Feed ingestion failed: {}".format(e),
                })
                env["portal.sync.log"].sudo().create({
                    "portal_id": portal.id,
                    "status": "failed",
                    "failed_count": 1,
                    "message": "Cron feed ingestion failed: {}".format(e),
                })
                total_errors += 1

        _logger.info(
            "Inbound feed processing completed. Created: %d, Updated: %d, "
            "Errors: %d", total_created, total_updated, total_errors,
        )
        return {
            "created": total_created,
            "updated": total_updated,
            "errors": total_errors,
        }

    @api.model
    def process_all_inbound_feeds(self):
        """Alias for process_inbound_feeds — kept for cron compatibility."""
        return self.process_inbound_feeds()

    def action_test_rapidapi_connection(self):
        """Fire a minimal smoke-test request at the RapidAPI host configured
        for this connector (api_endpoint) using api_key, and report the
        result as a notification + portal.sync.log entry.

        This checks reachability of the RapidAPI market-data API for this
        portal code. It is independent of the XML feed sync above — Bayut/
        Dubizzle/Property Finder syndication still goes through
        inbound_feed_url, not this key.
        """
        self.ensure_one()
        result = rapidapi_market_data_service.test_connection(
            self.code, self.api_key, self.api_endpoint,
        )

        self.write({
            "last_sync_date": fields.Datetime.now(),
            "last_sync_status": "success" if result["ok"] else "failed",
            "last_sync_message": "RapidAPI test ({}): {}".format(
                result["status_code"], result["message"],
            ),
        })
        self.env["portal.sync.log"].create({
            "portal_id": self.id,
            "status": "success" if result["ok"] else "failed",
            "message": "RapidAPI connectivity test: {}".format(result["message"]),
        })

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("RapidAPI Connection OK") if result["ok"] else _("RapidAPI Connection Failed"),
                "message": result["message"],
                "type": "success" if result["ok"] else "danger",
                "sticky": not result["ok"],
            },
        }
