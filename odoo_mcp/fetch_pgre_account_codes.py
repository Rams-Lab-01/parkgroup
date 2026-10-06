"""Fetch the real account codes from pgre.odoo.com (read-only, approved
2026-10-06) by reading account.account once per old company context (the code
is company-dependent and the CSV only captured one company's resolution).

Output: pgre_account_codes.json
  {old_account_id: {"owner_company": cid|None, "codes": {cid: code, ...}}}
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, r"C:\Parkgroup Data\odoo_mcp")
from pgre_client import OdooClient  # noqa: E402

OUT = Path(r"C:\Parkgroup Data\odoo_mcp\pgre_account_codes.json")
COMPANY_IDS = [1, 2, 3, 4, 5, 6, 7]

c = OdooClient()
out: dict[str, dict] = {}
for cid in COMPANY_IDS:
    ctx = {"allowed_company_ids": [cid], "company_id": cid, "lang": "en_US"}
    rows = c.execute_kw("account.account", "search_read", [], {
        "domain": [], "fields": ["id", "code", "name", "account_type"],
        "context": ctx, "limit": 0, "order": "id asc"}) or []
    n_code = 0
    for r in rows:
        code = r.get("code")
        rec = out.setdefault(str(r["id"]), {"owner_company": None, "codes": {},
                                            "name": r.get("name"),
                                            "account_type": r.get("account_type")})
        if code not in (None, "", False):
            rec["codes"][str(cid)] = str(code)
            n_code += 1
        # an account whose code resolves under this context is usable here;
        # owner-company detection: the first context that yields a code owns it
        if rec["owner_company"] is None and code not in (None, "", False):
            rec["owner_company"] = cid
    print(f"company {cid}: {len(rows)} accounts, {n_code} with code")

OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
multi = sum(1 for v in out.values() if len(v["codes"]) > 1)
diff = sum(1 for v in out.values()
           if len(set(v["codes"].values())) > 1)
print(f"accounts: {len(out)} | with codes: {sum(1 for v in out.values() if v['codes'])} "
      f"| multi-company codes: {multi} | differing codes: {diff}")
for k in ("6762", "4677", "4641", "2645", "4314"):
    print(k, "->", out.get(k))
