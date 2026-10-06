"""
Odoo RPC client for Parkgroup Real Estate (pgre.odoo.com).

Instance facts established by probing (see README):
  * ``pgre.odoo.com`` is an **Odoo.sh** branch (``Server: Odoo.sh``), version
    ``18.0+e``.  Odoo Online ``*.odoo.com`` and Odoo.sh look alike but differ.
  * The database is ``pgre-main-23539443`` -- the Odoo.sh naming convention.
    The subdomain ``pgre`` is NOT a valid database.
  * Odoo.sh exposes both ``/jsonrpc`` and ``/xmlrpc``; external RPC is on.
  * Odoo 18 has **no** native ``/mcp`` endpoint (that arrived in v19/v20), so an
    external stdio MCP server over the Odoo 18 external API is the only option.
  * ``parkgroup.sgctech.ai`` is a *different*, Cloudflare-gated host that 403s
    all programmatic access; it is not reachable from here.

Three authentication transports, tried in order
-----------------------------------------------
1. ``jsonrpc`` - API key as the user's password. Preferred, unattended.
2. ``xmlrpc``  - same credentials, legacy transport. Some hosts disable
   ``/jsonrpc`` (returns 403); this is the fallback.
3. ``session`` - **no API key needed.** Reuses the ``session_id`` cookie from
   your already-logged-in browser and calls ``/web/dataset/call_kw``. This is
   the workaround when you cannot mint an API key.

Set exactly one of these environment variables:

    PGRE_KEY          Odoo API key  (My Profile -> Account Security -> New API
                      Key; exactly 40 characters)
    PGRE_SESSION_ID   the ``session_id`` cookie value from your browser

Optional:

    PGRE_URL     base URL, default https://pgre.odoo.com
    PGRE_DB      database name; auto-discovered when unset
    PGRE_LOGIN   user login/email (required with PGRE_KEY)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import xmlrpc.client
from typing import Any, Iterable, Sequence

log = logging.getLogger("pgre.odoo")

DEFAULT_URL = "https://pgre.odoo.com"
DEFAULT_PAGE = 500
MAX_PAGE = 2000


class OdooError(RuntimeError):
    """Base error - any Odoo call that failed."""


class OdooAuthError(OdooError):
    """Credentials or session were rejected by the server."""


class OdooTransportError(OdooError):
    """RPC endpoint unreachable or disabled on the host."""


#: Odoo reports unreadable/invalid fields by name. Three shapes are matched:
#:   access the fields "a,b,c"                  (access-rights)
#:   Invalid field 'amount_credit'             (quoted)
#:   Invalid field account.move.line.state in leaf (...)   (unquoted, dotted)
_ACCESS_RIGHTS_RE = re.compile(r'access the fields ["\']([^"\']+)["\']', re.IGNORECASE)
_INVALID_FIELD_RE = re.compile(r"Invalid field '?([A-Za-z_][A-Za-z0-9_.]*)'?")

#: When the failure is about fields we keep the whole message: access-rights
#: errors list every unreadable column and must stay parseable.
FIELD_ERROR_KEEP = 20_000


def _is_field_error(message: str) -> bool:
    return bool(_ACCESS_RIGHTS_RE.search(message) or _INVALID_FIELD_RE.search(message))


def extract_inaccessible_fields(message: str) -> list[str]:
    """Pull the offending field names out of an Odoo error message.

    Handles both ``you do not have enough rights to access the fields "a,b"``
    and ``Invalid field 'a'.`` so a tolerant reader can shed them and retry.
    """
    found: list[str] = []
    for m in _ACCESS_RIGHTS_RE.finditer(message):
        found.extend(f.strip() for f in m.group(1).split(",") if f.strip())
    for m in _INVALID_FIELD_RE.finditer(message):
        found.append(m.group(1).strip())
    return [f for f in dict.fromkeys(found) if f and f != "id"]


class _BaseTransport:
    """Common contract every transport implements."""

    name = "base"
    password = ""

    def call(self, service: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        raise NotImplementedError

    def model_call(self, model: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        """Invoke an ORM method on ``model``."""
        raise NotImplementedError

    def probe(self) -> int | None:
        """Return the authenticated uid, or ``None`` if credentials are invalid."""
        raise NotImplementedError


class JsonRpcTransport(_BaseTransport):
    """Odoo JSON-RPC 2.0 over POST /jsonrpc."""

    name = "jsonrpc"

    def __init__(self, url: str, db: str, login: str, password: str, *, timeout: int = 180,
                 user_agent: str = "pgre-odoo-mcp/1.0", max_retries: int = 4) -> None:
        self.url = url.rstrip("/")
        self.db = db
        self.login = login
        self.password = password
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self._id = 0
        self._opener = urllib.request.build_opener()

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.url}/jsonrpc",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json",
                     "User-Agent": self.user_agent},
            method="POST",
        )
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", "replace")[:300]
                except Exception:
                    pass
                if exc.code == 403:
                    raise OdooTransportError(
                        f"/jsonrpc is disabled on {self.url} (HTTP 403); "
                        "falling back to XML-RPC."
                    ) from exc
                if exc.code in (401, 403):
                    raise OdooAuthError(f"HTTP {exc.code} - check API key and rights. {body}") from exc
                if exc.code in (408, 429, 500, 502, 503, 504) and attempt < self.max_retries:
                    self._sleep(attempt, f"HTTP {exc.code}")
                    continue
                raise OdooError(f"HTTP {exc.code} from {self.url}/jsonrpc: {body}") from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
                last = exc
                if attempt < self.max_retries:
                    self._sleep(attempt, f"transport error {exc}")
                    continue
        raise OdooTransportError(f"/jsonrpc unreachable after {self.max_retries} attempts: {last}")

    @staticmethod
    def _sleep(attempt: int, why: str) -> None:
        delay = min(2 ** attempt, 20)
        log.warning("Odoo retry in %ss (%s)", delay, why)
        time.sleep(delay)

    def call(self, service: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        self._id += 1
        params: dict[str, Any] = {"service": service, "method": method, "args": list(args)}
        if kwargs:
            params["kwargs"] = kwargs
        resp = self._post({"jsonrpc": "2.0", "method": "call", "params": params, "id": self._id})
        if resp.get("error"):
            err = resp["error"]
            data = err.get("data") or {}
            msg = data.get("message") or err.get("message") or "unknown error"
            # Do NOT truncate tightly: access-rights errors enumerate every
            # unreadable field, and a truncated list cannot be parsed by
            # extract_inaccessible_fields, so the tolerant reader would give up.
            msg = re.sub(r"\s+", " ", str(msg)).strip()
            raise OdooError(
                f"{service}.{method} failed [{err.get('code')}]: "
                f"{msg[:FIELD_ERROR_KEEP] if _is_field_error(msg) else msg[:600]}"
            )
        return resp.get("result")

    def model_call(self, model: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        uid = self.probe()
        return self.call("object", "execute_kw",
                         [self.db, uid, self.password, model, method, list(args), kwargs or {}])

    def probe(self) -> int | None:
        uid = self.call("common", "authenticate", [self.db, self.login, self.password, {}])
        return int(uid) if uid else None


class XmlRpcTransport(_BaseTransport):
    """Odoo XML-RPC. Kept for hosts where /jsonrpc is disabled."""

    name = "xmlrpc"

    def __init__(self, url: str, db: str, login: str, password: str, *, timeout: int = 180,
                 user_agent: str = "pgre-odoo-mcp/1.0", max_retries: int = 4) -> None:
        self.url = url.rstrip("/")
        self.db = db
        self.login = login
        self.password = password
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self._common = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/common", allow_none=True, use_datetime=False)
        self._models = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object", allow_none=True, use_datetime=False)
        self._uid: int | None = None

    def call(self, service: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                if service == "common":
                    return getattr(self._common, method)(*args)
                if service == "object":
                    return self._models.execute_kw(*args, **(kwargs or {}))
                raise OdooError(f"XML-RPC transport does not support service {service!r}")
            except xmlrpc.client.ProtocolError as exc:
                if exc.errcode in (401, 403):
                    raise OdooAuthError(f"HTTP {exc.errcode} - check API key and rights.") from exc
                if exc.errcode == 404 and attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 20))
                    continue
                raise OdooError(f"XML-RPC HTTP {exc.errcode}: {exc.errmsg}") from exc
            except xmlrpc.client.Fault as exc:
                text = str(exc)
                if "does not exist" in text and "database" in text.lower():
                    raise OdooError(f"Database {self.db!r} does not exist: {text[:300]}") from exc
                raise OdooError(f"XML-RPC fault: {text[:600]}") from exc
            except (urllib.error.URLError, OSError) as exc:
                last = exc
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 20))
                    continue
        raise OdooTransportError(f"/xmlrpc unreachable after {self.max_retries} attempts: {last}")

    def model_call(self, model: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        return self._models.execute_kw(self.db, self.probe(), self.password, model, method,
                                       list(args), kwargs or {})

    def probe(self) -> int | None:
        if self._uid is None:
            uid = self.call("common", "authenticate", [self.db, self.login, self.password, {}])
            self._uid = int(uid) if uid else None
        return self._uid


class SessionTransport(_BaseTransport):
    """Cookie-session transport - reuses your logged-in browser. No API key.

    Reads data through ``POST /web/dataset/call_kw``, the same endpoint Odoo's
    own web client uses, authenticated with the ``session_id`` cookie.

    This is the workaround when minting an API key is not possible.  The cookie
    is a **full account session**: treat it exactly like a password - it expires
    when you log out, and anyone holding it is you.  Prefer the API key for
    anything unattended.
    """

    name = "session"

    def __init__(self, url: str, db: str, session_id: str, *, timeout: int = 180,
                 user_agent: str = "pgre-odoo-mcp/1.0", max_retries: int = 4) -> None:
        self.url = url.rstrip("/")
        self.db = db
        self.session_id = session_id
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_retries = max_retries
        self._id = 0
        self._uid: int | None = None
        self._opener = urllib.request.build_opener()
        self._version: dict[str, Any] = {}

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        hdrs = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": self.user_agent,
            "X-Requested-With": "XMLHttpRequest",
            "Cookie": f"session_id={self.session_id}",
        }
        if extra:
            hdrs.update(extra)
        return hdrs

    def _get_json(self, path: str) -> dict[str, Any]:
        req = urllib.request.Request(f"{self.url}{path}", headers=self._headers(), method="GET")
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise OdooAuthError(
                    "The session_id cookie was rejected (it has expired or you were "
                    "logged out). Log in again and copy a fresh cookie."
                ) from exc
            raise OdooError(f"HTTP {exc.code} on {path}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise OdooTransportError(f"{path} unreachable: {exc}") from exc

    def probe(self) -> int | None:
        if self._uid is not None:
            return self._uid
        try:
            info = self._get_json("/web/session/get_session_info")
        except OdooAuthError:
            return None
        result = info.get("result") or {}
        uid = result.get("uid")
        if not uid or result.get("db") not in (None, self.db):
            return None
        self._uid = int(uid)
        self._version = result.get("server_version") or {}
        return self._uid

    def call(self, service: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        if service in ("common", "object"):
            raise OdooError(f"SessionTransport only supports ORM calls, not {service!r}")
        raise NotImplementedError

    def model_call(self, model: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        if self.probe() is None:
            raise OdooAuthError("Browser session is not valid; log in again and copy a fresh session_id.")
        self._id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"model": model, "method": method, "args": list(args), "kwargs": kwargs or {}},
            "id": self._id,
        }
        body = json.dumps(payload).encode("utf-8")
        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(f"{self.url}/web/dataset/call_kw",
                                         data=body, headers=self._headers(), method="POST")
            try:
                with self._opener.open(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                if data.get("error"):
                    err = data["error"]
                    msg = (err.get("data") or {}).get("message") or err.get("message") or "unknown"
                    raise OdooError(f"{model}.{method} failed: {str(msg)[:600]}")
                return data.get("result")
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise OdooAuthError("Browser session rejected; copy a fresh session_id.") from exc
                if exc.code in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 20))
                    continue
                raise OdooError(f"HTTP {exc.code} on /web/dataset/call_kw") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = exc
                if attempt < self.max_retries:
                    time.sleep(min(2 ** attempt, 20))
                    continue
        raise OdooTransportError(f"/web/dataset/call_kw unreachable: {last}")


# --------------------------------------------------------------------------- #
# Discovery
# --------------------------------------------------------------------------- #
def discover_dbs(url: str, *, timeout: int = 60) -> list[str]:
    """Ask the host which databases it serves. Empty list when blocked."""
    req = urllib.request.Request(f"{url.rstrip('/')}/web/database/list",
                                 headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return [str(x) for x in (payload.get("result") or [])]
    except Exception as exc:
        log.warning("Could not list databases on %s: %s", url, exc)
        return []


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class OdooClient:
    """Authenticated Odoo client with paging helpers.

    The transport (jsonrpc / xmlrpc / session) is chosen once during
    ``__init__`` and every ORM call is delegated to it, so the rest of the
    codebase never needs to know which one is in use.
    """

    def __init__(
        self,
        url: str | None = None,
        db: str | None = None,
        key: str | None = None,
        login: str | None = None,
        *,
        session_id: str | None = None,
        timeout: int = 180,
        transport: str | None = None,
    ) -> None:
        self.url = (url or os.environ.get("PGRE_URL") or DEFAULT_URL).rstrip("/")
        self.key = key or os.environ.get("PGRE_KEY") or ""
        self.login = login or os.environ.get("PGRE_LOGIN") or ""
        self.session_id = session_id or os.environ.get("PGRE_SESSION_ID") or ""

        if not (self.key or self.session_id):
            raise OdooError(
                "No credentials. Set either PGRE_KEY (an Odoo API key, 40 chars) "
                "or PGRE_SESSION_ID (the session_id cookie from your logged-in browser)."
            )

        self.db = db or os.environ.get("PGRE_DB") or ""
        if not self.db:
            found = discover_dbs(self.url, timeout=min(timeout, 60))
            if not found:
                raise OdooError(
                    f"Could not discover the database and PGRE_DB is unset. "
                    f"Tried {self.url}/web/database/list"
                )
            self.db = found[0]
            log.info("Auto-discovered database: %s", self.db)

        self.timeout = timeout
        ua = os.environ.get("PGRE_USER_AGENT", "pgre-odoo-mcp/1.0")

        # Odoo's API key acts as the password for the user's login.
        if self.key and self.login:
            rpc_login, rpc_password = self.login, self.key
        elif self.key:
            rpc_login, rpc_password = self.key, self.key
        else:
            rpc_login, rpc_password = self.login, self.login

        order = [transport] if transport else ["jsonrpc", "xmlrpc"]
        if not transport and self.session_id:
            order.append("session")

        self.transport: _BaseTransport | None = None
        self.uid: int | None = None
        failures: list[str] = []

        for name in order:
            try:
                if name == "session":
                    cand: _BaseTransport = SessionTransport(
                        self.url, self.db, self.session_id, timeout=timeout, user_agent=ua)
                elif name == "jsonrpc":
                    cand = JsonRpcTransport(self.url, self.db, rpc_login, rpc_password,
                                            timeout=timeout, user_agent=ua)
                else:
                    cand = XmlRpcTransport(self.url, self.db, rpc_login, rpc_password,
                                           timeout=timeout, user_agent=ua)
                uid = cand.probe()
            except OdooAuthError as exc:
                failures.append(f"{name}: {exc}")
                continue
            except OdooError as exc:
                failures.append(f"{name}: {exc}")
                continue
            if uid:
                self.transport = cand
                self.uid = int(uid)
                log.info("Authenticated via %s (uid=%s, db=%s)", name, uid, self.db)
                break
            failures.append(f"{name}: credentials/session rejected (uid=None)")

        if self.transport is None or self.uid is None:
            detail = "\n  - ".join(failures)
            raise OdooAuthError(
                f"Could not authenticate to {self.url} db={self.db!r}.\n"
                f"Tried:\n  - {detail}\n"
                "Likely causes:\n"
                "  * PGRE_KEY is not an Odoo API key (Odoo keys are exactly 40 chars)\n"
                "  * the key was revoked, or the login has no access to this database\n"
                "  * PGRE_SESSION_ID expired - log in again and copy a fresh cookie"
            )

    # -------------------------------------------------------------- plumbing
    @property
    def transport_name(self) -> str:
        return self.transport.name if self.transport else "none"

    def _rpc(self, service: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        if self.transport is None:
            raise OdooError("Client is not authenticated")
        return self.transport.call(service, method, args, kwargs)

    def execute_kw(self, model: str, method: str, args: Sequence[Any], kwargs: dict | None = None) -> Any:
        if self.transport is None:
            raise OdooError("Client is not authenticated")
        return self.transport.model_call(model, method, args, kwargs)

    # ---------------------------------------------------------------- reads
    def search_read(self, model: str, domain: list | None = None,
                    fields: Sequence[str] | None = None, *, offset: int = 0,
                    limit: int = DEFAULT_PAGE, order: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"domain": domain or [],
                                  "fields": list(fields) if fields else [],
                                  "limit": limit, "offset": offset}
        if order:
            kwargs["order"] = order
        return self.execute_kw(model, "search_read", [], kwargs) or []

    def iter_search_read(self, model: str, domain: list | None = None,
                         fields: Sequence[str] | None = None, *, page: int = DEFAULT_PAGE,
                         order: str | None = "id asc") -> Iterable[dict[str, Any]]:
        """Yield all matching records, paging transparently."""
        page = max(1, min(int(page), MAX_PAGE))
        offset = 0
        while True:
            rows = self.search_read(model, domain, fields, offset=offset, limit=page, order=order)
            if not rows:
                return
            yield from rows
            if len(rows) < page:
                return
            offset += page

    def search_count(self, model: str, domain: list | None = None) -> int:
        return int(self.execute_kw(model, "search_count", [], {"domain": domain or []}) or 0)

    def search_ids(self, model: str, domain: list | None = None, *,
                   limit: int = 0, order: str | None = None) -> list[int]:
        kwargs: dict[str, Any] = {"domain": domain or [], "limit": limit}
        if order:
            kwargs["order"] = order
        return list(self.execute_kw(model, "search", [], kwargs) or [])

    def read(self, model: str, ids: Sequence[int], fields: Sequence[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        return self.execute_kw(model, "read", [list(ids), list(fields)]) or []

    def fields_get(self, model: str, attributes: Sequence[str] | None = None) -> dict[str, dict]:
        kwargs: dict[str, Any] = {}
        if attributes:
            kwargs["attributes"] = list(attributes)
        return self.execute_kw(model, "fields_get", [], kwargs) or {}

    def search_read_tolerant(
        self,
        model: str,
        domain: list | None = None,
        fields: Sequence[str] | None = None,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE,
        order: str | None = None,
        dropped: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """``search_read`` that sheds unreadable fields instead of failing.

        Odoo raises when a key lacks rights to *any* requested field, e.g. HR
        columns on ``res.users`` for a non-HR user. For an export that must not
        abort, we parse the field list out of the error, drop it, and retry.

        Appends every dropped field name to ``dropped`` so the caller can report
        exactly what the key was not allowed to read.
        """
        working = list(fields) if fields else []
        for _attempt in range(6):
            try:
                return self.search_read(model, domain, working, offset=offset,
                                        limit=limit, order=order)
            except OdooError as exc:
                bad = extract_inaccessible_fields(str(exc))
                if not bad:
                    raise
                present = [f for f in bad if f in working]
                if not present:
                    raise
                for f in present:
                    working.remove(f)
                if dropped is not None:
                    dropped.extend(present)
                shown = ", ".join(present[:8])
                log.warning("Dropping %d unreadable field(s) on %s: %s%s",
                            len(present), model, shown,
                            " ..." if len(present) > 8 else "")
        return []

    def iter_search_read_tolerant(
        self,
        model: str,
        domain: list | None = None,
        fields: Sequence[str] | None = None,
        *,
        page: int = DEFAULT_PAGE,
        order: str | None = "id asc",
        dropped: list[str] | None = None,
    ) -> Iterable[dict[str, Any]]:
        """Paging generator over :meth:`search_read_tolerant`."""
        page = max(1, min(int(page), MAX_PAGE))
        offset = 0
        while True:
            rows = self.search_read_tolerant(model, domain, fields, offset=offset,
                                             limit=page, order=order, dropped=dropped)
            if not rows:
                return
            yield from rows
            if len(rows) < page:
                return
            offset += page

    def grouped_count(self, model: str, domain: list | None = None,
                      group_by: str = "move_type") -> dict[str, int]:
        groups = self.execute_kw(model, "read_group", [], {
            "domain": domain or [], "fields": [group_by], "groupby": [group_by],
            "lazy": True}) or []
        return {str(g.get(group_by) or "unset"): int(g.get(group_by + "_count", 0)) for g in groups}

    # ------------------------------------------------------------- metadata
    def about(self) -> dict[str, Any]:
        version_str: str | None = None
        serie: str | None = None
        if self.transport_name == "session":
            info = self.transport._get_json("/web/session/get_session_info").get("result", {})  # type: ignore[union-attr]
            version_str = info.get("server_version")
            serie = info.get("server_serie")
        else:
            ver = self._rpc("common", "version", []) or {}
            version_str = ver.get("server_version")
            serie = ver.get("server_serie")

        user = self.read("res.users", [self.uid], ["name", "login", "company_id", "partner_id"])
        comp = (self.read("res.company", [user[0]["company_id"][0]], ["name", "currency_id"])
                if user and user[0].get("company_id") else [])
        return {
            "url": self.url,
            "db": self.db,
            "uid": self.uid,
            "transport": self.transport_name,
            "server_version": version_str,
            "server_serie": serie,
            "user": user[0] if user else None,
            "company": comp[0] if comp else None,
        }


_CLIENT: OdooClient | None = None


def get_client(**kwargs: Any) -> OdooClient:
    """Process-wide cached client so MCP tools share one authenticated session."""
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = OdooClient(**kwargs)
    return _CLIENT