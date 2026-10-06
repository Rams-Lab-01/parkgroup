"""Rebuild the creation review lists from the rehearsal DB + creation map:
- accounts recoded because their old code was taken in the target
- accounts fuzzy-mapped onto an existing target account
- journals recoded for the same reason
Output: creation_review_2026-10-06.xlsx
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(r"C:\Parkgroup Data\odoo_mcp")
sys.path.insert(0, str(ROOT))
from reconcile import _add_sheet  # noqa: E402
from sgc_target_read import load_creds, rpc  # noqa: E402

DB = "sgc_mt_rehearsal"
creds = load_creds()
rid = [1]


def kw(m, meth, args, kwargs=None):
    return rpc(creds["ODOO_URL"], "object", "execute_kw",
               [DB, 2, creds["ODOO_API_KEY"], m, meth, args, kwargs or {}], rid)


creation = json.loads((ROOT / "creation_map_rehearsal.json").read_text(encoding="utf-8"))
cmap = creation["map"]
codes = json.loads((ROOT / "pgre_account_codes.json").read_text(encoding="utf-8"))
old_accounts = {int(r["old_id"]): r for r in
                csv.DictReader((ROOT / "migration_out/accounts.csv").open(encoding="utf-8-sig"))}
old_journals = {int(r["old_id"]): r for r in
                csv.DictReader((ROOT / "migration_out/journals.csv").open(encoding="utf-8-sig"))}
original_ids = {int(r["id"]) for r in
                csv.DictReader((ROOT / "target_out/accounts.csv").open(encoding="utf-8-sig"))}

# reverse: new account id -> old ids (created only)
new_to_olds: dict[int, list[int]] = defaultdict(list)
for oid, nid in cmap["accounts"].items():
    if isinstance(nid, int) and nid > 0 and nid not in original_ids:
        new_to_olds[nid].append(int(oid))
new_ids = sorted(new_to_olds)
created = kw("account.account", "read", [new_ids], {"fields": ["id", "code", "name"]})
recoded, fuzzy = [], []
for r in created:
    olds = new_to_olds[r["id"]]
    intended = ""
    for o in olds:
        c = codes.get(str(o), {}).get("codes", {})
        if c:
            intended = sorted(c.values())[0]
            break
    row = {"name": r["name"], "new_id": r["id"], "new_code": r["code"],
           "old_code": intended, "copies": len(olds)}
    if intended and r["code"] != intended:
        recoded.append(row)
for oid, nid in cmap["accounts"].items():
    if isinstance(nid, int) and nid in original_ids:
        r = old_accounts.get(int(oid))
        if r:
            fuzzy.append({"old_id": oid, "old_name": r["name"],
                          "new_id": nid, "old_code": ""})

# journals
jnew_to_olds: dict[int, list[int]] = defaultdict(list)
for oid, nid in cmap["journals"].items():
    if isinstance(nid, int) and nid > 0:
        jnew_to_olds[nid].append(int(oid))
jids = sorted(jnew_to_olds)
jcreated = kw("account.journal", "read", [jids], {"fields": ["id", "code", "name"]})
jrecoded = []
for r in jcreated:
    old = old_journals.get(jnew_to_olds[r["id"]][0], {})
    if str(old.get("code")) != r["code"]:
        jrecoded.append({"old_code": str(old.get("code", "")), "new_code": r["code"],
                         "name": r["name"], "new_id": r["id"]})

fuzzy_targets = {}
if fuzzy:
    tids = sorted({f["new_id"] for f in fuzzy})
    for r in kw("account.account", "read", [tids], {"fields": ["id", "name", "code"]}):
        fuzzy_targets[r["id"]] = r
for f in fuzzy:
    t = fuzzy_targets.get(f["new_id"], {})
    f["mapped_to"] = f"{t.get('code')} {t.get('name')}"

wb = Workbook()
wb.remove(wb.active)
_add_sheet(wb, "Accounts_Recoded", recoded)
_add_sheet(wb, "Accounts_Fuzzy_Mapped", fuzzy or [{"note": "(none)"}])
_add_sheet(wb, "Journals_Recoded", jrecoded)
out = ROOT / "creation_review_2026-10-06.xlsx"
wb.save(out)
print(f"accounts created: {len(created)} | recoded: {len(recoded)} | fuzzy: {len(fuzzy)}")
print(f"journals created: {len(jcreated)} | recoded: {len(jrecoded)}")
print("fuzzy:", [(f['old_name'][:34], f['mapped_to']) for f in fuzzy])
print("->", out.name)
