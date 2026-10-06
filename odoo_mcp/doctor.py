"""Connection doctor for pgre.odoo.com.

Run this FIRST. It tells you exactly what is wrong and, if the session
workaround is in play, gives you the precise ``PGRE_SESSION_ID`` command to run.

    # path A - API key (preferred)
    $env:PGRE_LOGIN = "renbran@parkgroup.ae"
    $env:PGRE_KEY    = "<40-char key>"
    python doctor.py

    # path B - reuse your logged-in browser session (no API key)
    $env:PGRE_SESSION_ID = "<cookie value>"
    python doctor.py

    # check instance facts only, no credentials at all
    python doctor.py --info

Exit codes: 0 ok, 2 auth failed, 3 connection failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pgre_client import OdooAuthError, OdooClient, OdooError, discover_dbs

HERE_DB_HINT = "pgre-main-23539443"


def show_instance_facts(url: str) -> None:
    print("=" * 74)
    print("INSTANCE FACTS  (no credentials needed)")
    print("=" * 74)
    dbs = discover_dbs(url)
    print(f"  url             : {url}")
    print(f"  databases       : {dbs or '(hidden)'}")
    if not dbs:
        print(f"  expected        : {HERE_DB_HINT}")
    print(f"  likely server   : Odoo.sh (db naming '<db>-main-<id>')")
    print()


def show_mcp_endpoints(url: str) -> None:
    """Confirm which MCP/RPC endpoints this Odoo actually offers.

    IMPORTANT: Odoo answers unknown routes with **HTTP 200 and an HTML 404
    page**, so HTTP status alone is misleading.  We therefore inspect the body
    and require it to actually look like a JSON-RPC response.
    """
    import urllib.error
    import urllib.request

    print("=" * 74)
    print("ENDPOINT SUPPORT  (body-inspected: Odoo returns 200 + HTML for unknowns)")
    print("=" * 74)
    probes: list[tuple[str, str, bytes, str, str]] = [
        ("POST", "/mcp",
         b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}',
         "application/json",
         "native MCP endpoint (Odoo 19+/20 only)"),
        ("POST", "/jsonrpc",
         b'{"jsonrpc":"2.0","method":"call","params":{"service":"common","method":"version","args":[]},"id":1}',
         "application/json",
         "JSON-RPC external API  <-- what this server uses"),
        ("POST", "/xmlrpc/2/common",
         b'<?xml version="1.0"?><methodCall><methodName>system.listMethods</methodName>'
         b'<params></params></methodCall>',
         "text/xml",
         "XML-RPC external API  <-- fallback"),
        ("POST", "/json/2/res.users/search", b'{"domain":[]}',
         "application/json",
         "JSON-2 external API (Odoo 19+ only)"),
    ]
    for method, path, body, ctype, desc in probes:
        req = urllib.request.Request(f"{url.rstrip('/')}{path}", data=body,
                                     headers={"Content-Type": ctype, "Accept": "*/*"},
                                     method=method)
        code: int | None = None
        raw = b""
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                code, raw = resp.status, resp.read(400)
        except urllib.error.HTTPError as exc:
            code, raw = exc.code, exc.read(400)
        except Exception:
            code, raw = None, b""

        text = raw.decode("utf-8", "replace").lstrip()
        head = text[:200].lower()
        # NB: XML-RPC responses also start with "<" (<?xml ...), so test for
        # actual HTML markup rather than any angle bracket.
        is_html = ("<!doctype html" in head or head.startswith("<html")
                   or "<html" in head)
        # A real endpoint answers with JSON-RPC or XML-RPC, not an HTML page.
        works = bool(code and code < 400 and not is_html)
        state = "available" if works else "NOT available"
        if code is None:
            state = "unreachable"
        elif code == 404:
            state = "not found"
        elif is_html and code == 200:
            state = "HTML error page"
        print(f"  {path:28} {str(code):>4}  {state:15} # {desc}")
    print()
    print("  => Odoo 18 has no native MCP endpoint, so this project ships an")
    print("     external stdio MCP server over JSON-RPC (XML-RPC as fallback).")
    print()


def run_checks(client: OdooClient) -> int:
    print("=" * 74)
    print("AUTHENTICATION")
    print("=" * 74)
    about = client.about()
    print(f"  transport       : {about['transport']}")
    print(f"  database        : {about['db']}")
    print(f"  uid             : {about['uid']}")
    print(f"  server version  : {about['server_version']}")
    user = about.get("user") or {}
    print(f"  user            : {user.get('name')} <{user.get('login')}>")
    comp = about.get("company") or {}
    print(f"  default company : {comp.get('name')}")
    print()

    print("=" * 74)
    print("READ PERMISSIONS")
    print("=" * 74)
    try:
        models = ["account.move", "account.payment", "account.move.line",
                  "account.journal", "res.partner", "account.account", "res.company"]
        for model in models:
            try:
                n = client.search_count(model, [])
                print(f"  {model:22} readable  {n:>9,} records")
            except OdooError as exc:
                print(f"  {model:22} BLOCKED    {str(exc)[:90]}")
    except Exception as exc:
        print(f"  ERROR: {exc}")
    print()

    print("=" * 74)
    print("COMPANIES  (multi-company check)")
    print("=" * 74)
    companies = client.read("res.company", client.search_ids("res.company", [], limit=50),
                            ["name", "currency_id"])
    for c in companies:
        ccy = (c.get("currency_id") or [None, "?"])[1]
        print(f"  id={c['id']:<5} {str(c.get('name')):52} {ccy}")
    print()

    print("=" * 74)
    print("DATA VOLUME  (how big is the export)")
    print("=" * 74)
    counts = {
        "customer_invoices": ("account.move", [("move_type", "=", "out_invoice"), ("state", "=", "posted")]),
        "customer_refunds": ("account.move", [("move_type", "=", "out_refund"), ("state", "=", "posted")]),
        "vendor_bills": ("account.move", [("move_type", "=", "in_invoice"), ("state", "=", "posted")]),
        "vendor_refunds": ("account.move", [("move_type", "=", "in_refund"), ("state", "=", "posted")]),
        "journal_entries": ("account.move", [("move_type", "=", "entry"), ("state", "=", "posted")]),
        "customer_payments": ("account.payment", [("payment_type", "=", "inbound"), ("partner_type", "=", "customer")]),
        "vendor_payments": ("account.payment", [("payment_type", "=", "outbound"), ("partner_type", "=", "supplier")]),
        "partners": ("res.partner", []),
        "journals": ("account.journal", []),
    }
    total = 0
    for label, (model, domain) in counts.items():
        try:
            n = client.search_count(model, domain)
            total += n
            print(f"  {label:22} {n:>9,}")
        except OdooError as exc:
            print(f"  {label:22} ERROR {str(exc)[:70]}")
    print(f"  {'-' * 22} {'-' * 9}")
    print(f"  {'TOTAL (approx)':22} {total:>9,}")
    print()

    print("=" * 74)
    print("SAMPLE ROW  (verifies field names against the live schema)")
    print("=" * 74)
    try:
        row = client.search_read("account.move",
                                 [("move_type", "=", "out_invoice"), ("state", "=", "posted")],
                                 ["name", "partner_id", "invoice_date", "amount_total",
                                  "amount_residual", "currency_id", "payment_state"],
                                 limit=1, order="invoice_date desc")
        print(json.dumps(row[0] if row else {}, indent=2, default=str))
    except OdooError as exc:
        print(f"  ERROR: {exc}")
    print()

    print("RESULT: READY - you can run export_data.py now.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose the pgre.odoo.com connection.")
    parser.add_argument("--info", action="store_true",
                        help="Only print instance facts, no credentials needed")
    parser.add_argument("--url", default=None)
    args = parser.parse_args()

    import os
    url = (args.url or os.environ.get("PGRE_URL") or "https://pgre.odoo.com").rstrip("/")

    show_instance_facts(url)
    show_mcp_endpoints(url)
    if args.info:
        return 0

    try:
        client = OdooClient(url=url)
    except OdooAuthError as exc:
        print("=" * 74)
        print("AUTHENTICATION FAILED")
        print("=" * 74)
        print(exc)
        print()
        print("-" * 74)
        print("HOW TO FIX - pick one")
        print("-" * 74)
        print("""
  Path A - API key (preferred, unattended)
    1. In Odoo: avatar -> My Profile -> Account Security tab
    2. "New API Key" -> Generate -> copy the key (shown once)
    3. It is EXACTLY 40 characters. A longer token is NOT an Odoo API key.
    4. PowerShell:
         $env:PGRE_LOGIN = "renbran@parkgroup.ae"
         $env:PGRE_KEY    = "<the 40-character key>"

  Path B - reuse the browser session you are already logged into
    1. Chrome: F12 -> Application -> Storage -> Cookies -> https://pgre.odoo.com
    2. Click "session_id" -> copy its Value
    3. PowerShell:
         $env:PGRE_SESSION_ID = "<cookie value>"
    Then run doctor.py again.

    Security note: the session_id cookie is a full account session - it
    behaves exactly like a password. Anyone holding it is you. Use the API
    key for anything unattended or automated.
""")
        return 2
    except OdooError as exc:
        print(f"\nCONNECTION FAILED\n\n{exc}\n")
        return 3

    return run_checks(client)


if __name__ == "__main__":
    raise SystemExit(main())