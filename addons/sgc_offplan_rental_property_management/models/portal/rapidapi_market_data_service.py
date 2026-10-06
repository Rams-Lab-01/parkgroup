# -*- coding: utf-8 -*-
#
# RapidAPI Market Data Service — connectivity test for the RapidAPI-hosted
# market-data APIs (Bayut/Property Finder/Dubizzle listings & transactions).
# ------------------------------------------------------------------
# This is deliberately separate from inbound_feed_service.py: that module
# handles the real portal-partner XML feed exchange (Bayut/Dubizzle pushing
# us their own listing feed via Basic Auth). This module instead talks to
# third-party RapidAPI-hosted scraper/market-data APIs — a different
# integration shape, used for connectivity checks and market data lookups,
# not for the outbound/inbound listing-syndication pipeline.
#
# Each RapidAPI host requires its own subscription on the RapidAPI account
# even when a single x-rapidapi-key is shared across hosts, so "connected"
# for one portal code does not imply "connected" for another.
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

_HTTP_TIMEOUT = 15

# Known-good smoke-test request per portal code: (method, default host,
# path, query string or None, JSON body dict or None).
_TEST_REQUESTS = {
    "bayut": (
        "GET",
        "uae-real-estate3.p.rapidapi.com",
        "/autocomplete",
        "query=dubai",
        None,
    ),
    "property_finder": (
        "POST",
        "property-finder-api.p.rapidapi.com",
        "/area/get-by-url",
        None,
        {"url": "https://www.propertyfinder.ae/en/area-insights/dubai/palm-jumeirah"},
    ),
    "dubizzle": (
        "POST",
        "dubizzle-api.p.rapidapi.com",
        "/scrapers/api/dubizzle/product/listing-by-url",
        None,
        {"url": "https://rak.dubizzle.com/motors/used-cars/"},
    ),
}


def test_connection(portal_code, api_key, api_endpoint=None):
    """Fire a minimal, known-valid request at the RapidAPI host for
    ``portal_code`` and report whether the key/host combination is
    actually reachable and authorized.

    Returns a dict: {"ok": bool, "status_code": int|None, "message": str}.
    Never raises — callers (cron/button) decide how to surface failures.
    """
    if portal_code not in _TEST_REQUESTS:
        return {
            "ok": False,
            "status_code": None,
            "message": (
                "No RapidAPI test request configured for portal code "
                "'{}'. Supported: {}.".format(
                    portal_code, ", ".join(sorted(_TEST_REQUESTS)),
                )
            ),
        }

    if not api_key:
        return {
            "ok": False,
            "status_code": None,
            "message": "No RapidAPI key configured (api_key field is empty).",
        }

    method, default_host, path, query, body = _TEST_REQUESTS[portal_code]
    host = (api_endpoint or default_host).strip()
    url = "https://{}{}".format(host, path)
    if query:
        url = "{}?{}".format(url, query)

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(url, data=data, method=method)
    req.add_header("x-rapidapi-host", host)
    req.add_header("x-rapidapi-key", api_key)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    # RapidAPI's edge (Cloudflare) blocks Python's default urllib UA as a
    # bot signature — without this every request 403s before it even
    # reaches RapidAPI's own auth/subscription check.
    req.add_header("User-Agent", "curl/8.0")

    try:
        with urlopen(req, timeout=_HTTP_TIMEOUT) as response:
            status_code = response.getcode()
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        status_code = e.code
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
    except URLError as e:
        _logger.error("RapidAPI connectivity test failed for %s (%s): %s",
                       portal_code, host, e.reason)
        return {
            "ok": False,
            "status_code": None,
            "message": "Could not reach {}: {}".format(host, e.reason),
        }
    except Exception as e:  # noqa: BLE001
        _logger.exception("Unexpected error testing RapidAPI connection for %s", portal_code)
        return {
            "ok": False,
            "status_code": None,
            "message": "Unexpected error: {}".format(e),
        }

    ok, message = _interpret_response(status_code, raw)
    return {"ok": ok, "status_code": status_code, "message": message}


def _interpret_response(status_code, raw_body):
    """RapidAPI's gateway wraps subscription/routing errors in a 200 or
    40x JSON body rather than always using the HTTP status code, so we
    inspect the body for the known error shapes before trusting the
    status code alone.
    """
    body_snippet = raw_body[:300]

    try:
        parsed = json.loads(raw_body)
    except (ValueError, TypeError):
        parsed = None

    # Check RapidAPI's own known error shapes first — these are specific
    # and reliable regardless of HTTP status code.
    if isinstance(parsed, dict) and parsed.get("message") == "You are not subscribed to this API.":
        return False, "Not subscribed to this API on RapidAPI."
    if isinstance(parsed, dict) and parsed.get("status_code") == 401:
        return False, "API rejected the key (401 in response body): {}".format(body_snippet)

    if status_code == 404:
        return False, "Endpoint not found (wrong host/path): {}".format(body_snippet)
    if status_code == 401:
        return False, "Unauthorized (invalid/missing key): {}".format(body_snippet)
    if status_code == 403:
        # 403 alone is ambiguous: RapidAPI subscription block and Cloudflare
        # edge block both use it. Surface the raw body instead of guessing.
        return False, "HTTP 403 Forbidden: {}".format(body_snippet)

    if status_code and 200 <= status_code < 300:
        return True, "Reachable, key accepted. Sample response: {}".format(body_snippet)

    return False, "Unexpected HTTP {}: {}".format(status_code, body_snippet)
