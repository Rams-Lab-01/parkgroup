"""Read the PARK Group target instance (parkgroup.sgctech.ai, db sgc_mt_parkgroup)
into ``target_out\\`` CSVs, feeding the old_id -> new_id migration mapping.

Credentials come from the existing odoo-mcp setup (user approved 2026-10-06):
``C:\\Users\\USER\\GensparkCode\\odoo-mcp\\.env`` (fallback: mcp.odoo.environment
in ``~/.config/gencode/opencode.json``).  No secret is ever printed.

Cloudflare note (root cause of the old "403 on every path" blocker): the
sgctech.ai zone bans the exact User-Agent string ``Python-urllib`` with error
1010, so every request below sends a normal browser User-Agent.
"""

from __future__ import annotations

import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Parkgroup Data\odoo_mcp")
OUT = ROOT / "target_out"
ODOO_MCP_ENV = Path(r"C:\Users\USER\GensparkCode\odoo-mcp\.env")
OPENCODE_CFG = Path.home() / ".config" / "gencode" / "opencode.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

DATASETS = {
    "companies": ("res.company", ["id", "name"]),
    "partners": ("res.partner",
                 ["id", "name", "email", "phone", "vat", "is_company",
                  "company_type", "active", "parent_id"]),
    "accounts": ("account.account", ["id", "code", "name", "account_type"]),
    "journals": ("account.journal", ["id", "code", "name", "type"]),
    "currencies": ("res.currency", ["id", "name", "symbol", "active"]),
    "countries": ("res.country", ["id", "code", "name"]),
    "taxes": ("account.tax", ["id", "name", "amount", "type_tax_use",
                              "company_id", "active"]),
    "payment_terms": ("account.payment.term", ["id", "name", "active"]),
    "products": ("product.product", ["id", "name", "default_code", "type", "active"]),
    "users": ("res.users", ["id", "login", "name", "active"]),
    "fiscal_positions": ("account.fiscal.position", ["id", "name", "company_id",
                                                     "country_id"]),
    "analytic_accounts": ("account.analytic.account", ["id", "name", "code"]),
    "payment_methods": ("account.payment.method", ["id", "name", "code",
                                                   "payment_type"]),
    "units": ("property.details", ["id", "name", "unit_number", "project_id",
                                   "floor"]),
    "projects": ("property.project", ["id", "name"]),
    "moves_existing": ("account.move", ["id", "name", "move_type", "state",
                                        "date", "amount_total", "partner_id",
                                        "journal_id"]),
    "payments_existing": ("account.payment", ["id", "name", "amount", "state",
                                              "date", "partner_id", "journal_id"]),
}


def load_creds() -> dict[str, str]:
    creds: dict[str, str] = {}
    if ODOO_MCP_ENV.exists():
        for line in ODOO_MCP_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            creds[k.strip()] = v.strip().strip('"').strip("'")
    needed = ("ODOO_URL", "ODOO_DB", "ODOO_USER", "ODOO_API_KEY")
    if not all(creds.get(k) for k in needed):
        if OPENCODE_CFG.exists():
            cfg = json.loads(OPENCODE_CFG.read_text(encoding="utf-8"))
            env = (cfg.get("mcp", {}).get("odoo", {}) or {}).get("environment", {}) or {}
            for k in needed:
                creds.setdefault(k, str(env.get(k) or "").strip())
    missing = [k for k in needed if not creds.get(k)]
    if missing:
        raise SystemExit(f"missing credential(s): {', '.join(missing)} "
                         f"(looked in {ODOO_MCP_ENV} and {OPENCODE_CFG})")
    return creds


def rpc(url: str, service: str, method: str, args: list, req_id: list[int],
        timeout: int = 120) -> object:
    payload = json.dumps({"jsonrpc": "2.0", "method": "call",
                          "params": {"service": service, "method": method,
                                     "args": args},
                          "id": req_id[0]}).encode()
    req_id[0] += 1
    req = urllib.request.Request(
        url.rstrip("/") + "/jsonrpc", data=payload,
        headers={"Content-Type": "application/json", "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        body = exc.read(300).decode("utf-8", "replace")
        raise SystemExit(f"HTTP {exc.code} from {url} (cf-ray {exc.headers.get('cf-ray')}): {body}")
    if data.get("error"):
        err = data["error"]
        msg = (err.get("data") or {}).get("message") or err.get("message")
        raise SystemExit(f"Odoo error: {msg}")
    return data.get("result")


def connect() -> tuple[dict[str, str], int, list[int]]:
    creds = load_creds()
    url, db = creds["ODOO_URL"], creds["ODOO_DB"]
    req_id = [1]
    version = rpc(url, "common", "version", [], req_id)
    uid = rpc(url, "common", "authenticate",
              [db, creds["ODOO_USER"], creds["ODOO_API_KEY"], {}], req_id)
    if not isinstance(uid, int) or uid <= 0:
        raise SystemExit("authentication failed (uid %r)" % (uid,))
    print(f"connected: {url}  db={db}  server={version.get('server_version')}  uid={uid}")
    return creds, uid, req_id


def search_read(creds: dict[str, str], uid: int, req_id: list[int],
                model: str, fields: list[str]) -> list[dict]:
    def call(fs: list[str]) -> list[dict]:
        return rpc(creds["ODOO_URL"], "object", "execute_kw",
                   [creds["ODOO_DB"], uid, creds["ODOO_API_KEY"], model,
                    "search_read", [[]], {"fields": fs, "order": "id asc"}],
                   req_id)
    try:
        return call(fields)
    except SystemExit:
        if "active" in fields:
            return call([f for f in fields if f != "active"])
        raise


def write_csv(path: Path, rows: list[dict]) -> None:
    cols: list[str] = []
    for r in rows:
        for k in r:
            if k not in cols:
                cols.append(k)
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: _flat(r.get(k)) for k in cols})


def _flat(v: object) -> object:
    if isinstance(v, list) and len(v) == 2 and isinstance(v[1], str):
        return f"{v[0]}|{v[1]}"
    if isinstance(v, bool) or v is None:
        return v
    return v


def main() -> int:
    OUT.mkdir(exist_ok=True)
    creds, uid, req_id = connect()
    for name, (model, fields) in DATASETS.items():
        print(f"reading {model} ...")
        rows = search_read(creds, uid, req_id, model, fields)
        write_csv(OUT / f"{name}.csv", rows)
        print(f"  {len(rows):,} records -> target_out\\{name}.csv")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
