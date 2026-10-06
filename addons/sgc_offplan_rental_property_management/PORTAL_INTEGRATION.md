# Listing Syndication Portal — Integration Status

Scope: `models/portal/*`, `controllers/xml_feed_controller.py`, `controllers/webhook_controller.py`.
(Unrelated to `controllers/portal.py`, the self-service tenant/landlord/customer portal.)

## What is implemented

- **Outbound feed** (`GET /portal-feed/<portal_code>?token=...`): generates a real,
  well-formed XML listing feed from `property.details` records (state
  `available`/`rented`, active only), covering reference number, title,
  description, property type, sale price or rent price, location
  (address/city/region/state/country/project), bedrooms/bathrooms, area,
  image URLs (`/web/image/...`), and agent contact info (owner, falling
  back to landlord). Existing HMAC token gate (`hmac.compare_digest`) is
  unchanged. Unknown/unauthorized portal codes still get a clean 400/401;
  any unexpected error during generation returns a clean `<feed><status>error</status></feed>`
  with HTTP 500 instead of crashing.
- **Inbound webhook** (`POST /portal-webhook/<portal_code>`, jsonrpc):
  parses an incoming JSON payload into a `portal.lead` record and links it
  to a `property.portal.line` when a matching `property_reference` is
  found. Every outcome (success or failure) is logged to `portal.sync.log`.
  Malformed payloads (missing name, bad email/phone format per
  `portal.lead`'s own constraints, non-object bodies) are caught and
  logged as a failed sync — the request never crashes, it returns a clean
  `{"status": "error", ...}` response.

## What is intentionally deferred

Real Bayut / Property Finder / Dubizzle push/pull integration requires:

1. Their actual API credentials (`portal.connector.api_key` / `api_secret` / `api_endpoint`)
   — none exist yet.
2. Confirmed field-mapping/XSD per portal — the feed above uses one
   generic schema modeled on the field set common across these portals'
   publicly documented listing feeds, not any one portal's exact spec.
3. Confirmed inbound webhook payload shape per portal — the schema
   documented at the top of `webhook_controller.py` is an assumption,
   not a verified spec.

None of the above blocks this phase: per client direction this is a
**framework-only** build, verified with synthetic/mocked payloads. Once
a partner/API agreement exists, swapping in real credentials and
adjusting `_build_property_element` / `_parse_lead_payload` to match the
real spec is a targeted, contained change — the property.details ->
feed pipeline and the webhook -> `portal.lead` pipeline do not need to
be rebuilt.

## Known model gaps affecting the feed

- `property.details` has no dedicated RERA/permit-number field, so the
  feed emits an empty `<permit_number/>` element rather than guessing.
- `property.details` has no listing-level rent frequency field; the feed
  assumes annual rent quoting (`<frequency>yearly</frequency>`), which is
  the UAE-market convention, until a real field/portal spec says otherwise.
