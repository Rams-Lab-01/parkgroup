# -*- coding: utf-8 -*-
#
# Property Feed Ingestion — HTTP entry point.
# ------------------------------------------------------------------
# Thin wrapper over the shared inbound_feed_service module. All real
# fetch/parse/process logic lives in that module so the scheduled cron
# job can reuse it without duplicating code.
#
# CREDENTIAL GAP (intentional, not a bug): see the docstring at the top
# of inbound_feed_service.py — the XML schema is a reasonable assumption,
# not a real Bayut/Dubizzle spec.
from odoo import _, fields, http
from odoo.http import request
import logging

from ..models.portal import inbound_feed_service

_logger = logging.getLogger(__name__)


class InboundFeedController(http.Controller):

    @http.route(
        ["/portal-feed-ingest/<string:portal_code>"],
        type="http",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def portal_feed_ingest(self, portal_code, **kwargs):
        """Trigger feed ingestion for a specific portal (also used by cron)."""
        # Input validation
        if not portal_code or not portal_code.replace("_", "").isalnum():
            return request.make_response(
                "Invalid portal code",
                [("Content-Type", "text/plain")],
                status=400,
            )

        portal = request.env["portal.connector"].sudo().search(
            [("code", "=", portal_code)],
            limit=1,
        )
        if not portal:
            return request.make_response(
                "Unknown portal",
                [("Content-Type", "text/plain")],
                status=404,
            )

        if not portal.inbound_feed_url:
            return request.make_response(
                "No inbound feed URL configured for this portal",
                [("Content-Type", "text/plain")],
                status=400,
            )

        try:
            feed_xml = inbound_feed_service.fetch_feed_xml(
                request.env,
                portal.inbound_feed_url,
                portal.inbound_feed_username,
                portal.inbound_feed_password,
            )
            created, updated, errors = inbound_feed_service.process_feed_properties(
                request.env, portal, feed_xml,
            )
            self._record_sync_result(
                portal, "success" if not errors else "partial",
                created, updated, errors,
                _(
                    "Feed ingest: %(created)d new, %(updated)d updated, "
                    "%(err)d errors",
                    created=created, updated=updated, err=len(errors),
                ),
            )
            return request.make_response(
                "Feed processed successfully: {} new, {} updated properties".format(
                    created, updated,
                ),
                [("Content-Type", "text/plain")],
                status=200,
            )
        except Exception as e:
            _logger.exception("Feed ingestion failed for portal %s", portal.code)
            self._record_sync_result(
                portal, "failed", 0, 0, [str(e)],
                "Feed ingestion failed: {}".format(e),
            )
            return request.make_response(
                "Feed ingestion failed: {}".format(e),
                [("Content-Type", "text/plain")],
                status=500,
            )

    def _record_sync_result(self, portal, status, created, updated, errors,
                            message):
        portal.sudo().write({
            "last_sync_date": fields.Datetime.now(),
            "last_sync_status": status,
            "last_sync_message": message,
        })
        request.env["portal.sync.log"].sudo().create({
            "portal_id": portal.id,
            "status": status,
            "created_count": created,
            "updated_count": updated,
            "failed_count": len(errors),
            "message": message,
        })