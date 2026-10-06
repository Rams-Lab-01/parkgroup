# SGC Offplan Rental & Property Management — Production Deployment Guide

Target: Odoo 19.0, community edition. Deployment model: **ten-tenant
production** — one shared application server, one shared PostgreSQL server,
**one PostgreSQL database + one restricted role + one Odoo container per
tenant**, one shared codebase (this module) for all ten.

## 1. Isolation model

| Layer | Guarantee |
|---|---|
| Database | One `sgc_<tenant>` database per tenant; no row, company or domain bridging |
| PostgreSQL role | `sgc_<tenant>_app` owns exactly one database, is `NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION`, `CONNECTION LIMIT 40` |
| Process | One Odoo container per tenant on a distinct host port; a crash or memory spike is contained |
| Configuration | `list_db = False` and `dbfilter = ^sgc_<tenant>$` in each tenant conf, so a tenant process can only ever see its own database |
| Secrets | Feed tokens and webhook secrets are seeded per record by Python defaults (`secrets.token_urlsafe(32)`); two tenant databases never share a credential |

The module's own company/record rules (13 `ir.rule` records in
`security/security.xml` + portal rules) remain as defence-in-depth for
multi-company setups *inside* a tenant; the tenancy boundary itself is the
database + role, not Odoo companies.

## 2. First deployment

```bash
cd <module>/ops
cp ops.env.example ops.env        # fill in TENANTS, PG credentials, paths
# one line per tenant in $PGAPPPASSWORD_FILE:  <slug>:<password>
./provision.sh jvc                # repeat per tenant
```

`provision.sh` refuses to overwrite an existing database, creates the role and
database, writes a hardened `odoo.conf`, installs this module with
`--without-demo=all`, and prints the tenant's host port (base port + index).

### Hardened odoo.conf (written automatically per tenant)

- `admin_passwd` randomized per tenant (retrieve from the conf file if ever
  needed; never printed to the console)
- `db_user` = the tenant's restricted role, never `postgres`/`odoo` superuser
- `list_db = False`, `dbfilter = ^<db>$`, `proxy_mode = True`
- `workers = 2 * CPU + 1`, `limit_memory_hard/soft` sized per worker
- `max_cron_threads = 1` per tenant

**Cron capacity constraint (explicit):** each tenant runs up to four module
crons (tenancy reminder, contract status, portal sync poll, feed-related
housekeeping) with 1 cron thread each. Ten tenants = ~10 concurrent cron
threads + workers on the shared host. Size CPU/memory accordingly and keep
`sync_frequency` on portal connectors at `15min` or slower for tenants that
do not need real-time.

## 3. Reverse proxy & TLS

Terminate TLS at nginx/Caddy on the host, proxy each tenant by subdomain:

```
jvc.example.com  -> 127.0.0.1:8070   # port_of("jvc") with PORT_BASE=8069
...
```

`proxy_mode = True` is already set; the proxy must send `X-Forwarded-Proto`,
`X-Forwarded-Host` and `X-Real-IP` (the login-bruteforce protection and the
webhook IP logging rely on it).

## 4. Brute-force protection (fail2ban)

Install `ops/fail2ban/odoo-login.conf` as
`/etc/fail2ban/filter.d/odoo-login.conf` and add the jail snippet from the top
of that file. The portal (`auth='public'` feed endpoints, `/web/login`) is
internet-facing; login failures are logged per tenant and banned centrally.

## 5. Backups — the filestore trap

A database-only dump is NOT a backup of an Odoo tenant: documents, property
images and portal uploads live in the **filestore on disk**
(`data_dir/filestore/<db>`). `ops/backup.sh` bundles `pg_dump -Fc` **plus**
the filestore tarball into one archive, verifies the archive, and keeps the
last 14 per tenant. Schedule it:

```
15 2 * * *  /opt/sgc/addons/sgc_offplan_rental_property_management/ops/backup.sh
```

`ops/restore.sh` restores into a sidecar database first, sanity-checks it
(`res_users` non-empty), and only swaps databases after a typed confirmation.
`ops/upgrade_tenant.sh` always takes a backup first, then upgrades a single
tenant with `-u` and fails fast on errors. `ops/deprovision.sh` is
double-guarded (flag + typed confirmation) and takes a final witness backup.

## 6. Portal syndication (feed + webhook)

- **Outbound feed** `/portal-feed/<code>?token=<token>`: token per connector,
  constant-time comparison, fail-closed when blank, usage tracked
  (`token_last_used`, `token_usage_count`). Pagination: `offset` / `limit`
  query params, default `limit=200`, hard cap `1000`; the response echoes
  `offset`, `limit`, `count`. Give portals the paging contract instead of
  letting them pull unbounded catalogues.
- **Inbound leads** `/portal-webhook/<code>`: the portal must send the JSON-RPC
  body (`{"jsonrpc":"2.0","id":1,"method":"call","params":{...payload...}}`)
  and an `X-SGC-Signature: sha256=<hex>` header where `<hex>` is
  HMAC-SHA256 over the **exact raw request bytes** with the connector's
  `webhook_secret`. Unsigned, wrong-signed and blank-secret requests are
  rejected and logged to `portal.sync.log`. Regenerate the secret from the
  connector form button whenever a portal's credential leaks.

Reference signer (Python):

```python
import hmac, hashlib, json, requests
body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "call",
                   "params": {"name": "...", "email": "..."}}).encode()
sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
requests.post(url, data=body, headers={
    "Content-Type": "application/json",
    "X-SGC-Signature": "sha256=" + sig,
})
```

## 7. Upgrades & versioning

The manifest is at `19.0.2.12`. **Every schema change from now on needs a
migration script** under `migrations/<new-version>/` — tenants upgrade one at
a time via `ops/upgrade_tenant.sh` (backup first is built in). Never edit
`migrations/` of a released version.

## 8. Pre-flight checklist (all verified on Odoo 19.0 for this release)

- [x] Fresh-database install: zero errors (`Modules loaded.`)
- [x] Upgrade pass `-u`: zero errors
- [x] All XML valid against Odoo 19 `import_xml.rng`
- [x] All Python compiles; static audit: no dangling refs, no duplicate
      routes/models/ACL gaps
- [x] `/web/login`, `/offplan/properties` render anonymously
- [x] `/my/dashboard` renders for an authenticated portal user
- [x] Feed rejects missing token (401), serves XML with token
- [x] Webhook rejects unsigned / wrong-signature payloads; a valid signature
      creates a `portal.lead`
- [x] `portal.connector` create auto-seeds random `webhook_secret` +
      `xml_feed_token`
- [ ] Your infra: Postgres tuned (work_mem, max_connections >= tenants x 12),
      TLS, fail2ban, backup cron, monitoring — use `ops/` for the standard
      path
