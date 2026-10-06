"""Create the reference records the migration needs in the TARGET, as approved
2026-10-06: missing accounts, journals, partners and 14 inactive users.

Safety: dry-run by default; --apply writes.  Refuses to run against the live
production DB (sgc_mt_parkgroup) unless --allow-prod is passed explicitly.
Writes the old_id -> new_id creation map so the importer can resolve every
reference afterwards.

Usage:
  python create_reference_records.py                  # dry-run on rehearsal
  python create_reference_records.py --apply          # writes to rehearsal
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"C:\Parkgroup Data\odoo_mcp")
sys.path.insert(0, str(ROOT))
from reconcile import norm_name  # noqa: E402
from sgc_target_read import load_creds, rpc  # noqa: E402
from import_moves import formalize  # noqa: E402

OLD = ROOT / "migration_out"
NEW = ROOT / "target_out"
MAP_JSON = ROOT / "target_mapping_2026-10-06.json"
CODES_JSON = ROOT / "pgre_account_codes.json"
PROD_DB = "sgc_mt_parkgroup"

MOVE_DATASETS = ("invoices", "bills", "journal_entries", "customer_refunds",
                 "vendor_refunds", "receipts")


def s(value: object) -> str:
    if value in (None, "", "False", "None"):
        return ""
    return str(value).strip()


def pref(value: str) -> tuple[str, int] | None:
    m = re.match(r"^(.*?)\s*\((\d+)\)$", s(value))
    return (m.group(1), int(m.group(2))) if m else None


def load(folder: Path, name: str) -> list[dict]:
    with (folder / f"{name}.csv").open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


class Target:
    def __init__(self, db: str, apply: bool):
        self.creds = load_creds()
        self.db = db
        self.apply = apply
        self.uid = rpc(self.creds["ODOO_URL"], "common", "authenticate",
                       [db, self.creds["ODOO_USER"], self.creds["ODOO_API_KEY"], {}], [1])
        self.rid = [2]
        self.created = Counter()
        self.skipped: list[dict] = []
        self.map: dict[str, dict] = {"accounts": {}, "journals": {},
                                     "partners": {}, "users": {}}

    def kw(self, model: str, method: str, args: list, kwargs: dict | None = None):
        return rpc(self.creds["ODOO_URL"], "object", "execute_kw",
                   [self.db, self.uid, self.creds["ODOO_API_KEY"], model, method,
                    args, kwargs or {}], self.rid)

    def create(self, model: str, vals: dict, label: str, old_ids: list[int],
               bucket: str) -> bool:
        if not self.apply:
            for oid in old_ids:
                self.map[bucket][str(oid)] = -1
            self.created[bucket] += 1
            return True
        try:
            new_id = self.kw(model, "create", [vals])
        except SystemExit as exc:
            self.skipped.append({"bucket": bucket, "label": label,
                                 "reason": str(exc)[:160]})
            return False
        for oid in old_ids:
            self.map[bucket][str(oid)] = int(new_id)
        self.created[bucket] += 1
        return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sgc_mt_rehearsal")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--allow-prod", action="store_true")
    ap.add_argument("--map-out", default=str(ROOT / "creation_map_rehearsal.json"))
    args = ap.parse_args()
    if args.db == PROD_DB and not args.allow_prod:
        raise SystemExit("refusing to write to the production DB without --allow-prod")

    mapping = json.loads(MAP_JSON.read_text(encoding="utf-8"))
    codes = json.loads(CODES_JSON.read_text(encoding="utf-8"))
    t = Target(args.db, args.apply)
    print(f"target db={args.db} uid={t.uid} apply={args.apply}")

    # resume-safety: keep ids from a previous apply so a re-run never duplicates
    if Path(args.map_out).exists():
        try:
            prior = json.loads(Path(args.map_out).read_text(encoding="utf-8"))
            for bucket in ("accounts", "journals", "partners", "users"):
                t.map[bucket].update(prior.get("map", {}).get(bucket, {}))
            print("prior creation map loaded:", {k: len(v) for k, v in t.map.items()})
        except (json.JSONDecodeError, OSError):
            pass

    def already(bucket: str, oid: int) -> bool:
        v = t.map[bucket].get(str(oid))
        return isinstance(v, int) and v > 0

    # ---------------- compute create lists (full old-id copies) -------------
    ml = load(OLD, "move_lines")
    moves = [r for ds in MOVE_DATASETS for r in load(OLD, ds)]
    payments = load(OLD, "payments")
    accounts_rows = load(OLD, "accounts")
    journals_rows = load(OLD, "journals")
    partners_rows = load(OLD, "partners")
    users_rows = load(OLD, "users")

    acc_by_id = {int(r["old_id"]): r for r in accounts_rows}
    j_by_id = {int(r["old_id"]): r for r in journals_rows}
    p_by_id = {int(r["old_id"]): r for r in partners_rows}

    used_acc: Counter = Counter()
    for r in ml:
        p = pref(r.get("account_id", ""))
        if p and str(p[1]) not in mapping.get("accounts", {}):
            used_acc[p[1]] += 1
    acc_groups: dict[str, dict] = {}
    for oid in used_acc:
        r = acc_by_id.get(oid, {})
        key = norm_name(s(r.get("name")))
        g = acc_groups.setdefault(key, {"name": s(r.get("name")), "ids": [],
                                        "types": Counter(), "lines": 0})
        g["ids"].append(oid)
        g["types"][s(r.get("account_type"))] += 1
        g["lines"] += used_acc[oid]

    used_j: Counter = Counter()
    for r in moves + payments:
        p = pref(r.get("journal_id", ""))
        if p and str(p[1]) not in mapping.get("journals", {}):
            used_j[p[1]] += 1
    j_groups: dict[tuple, dict] = {}
    for oid in used_j:
        r = j_by_id.get(oid, {})
        key = (s(r.get("code")), s(r.get("name")), s(r.get("type")))
        g = j_groups.setdefault(key, {"code": key[0], "name": key[1], "type": key[2],
                                      "ids": [], "records": 0})
        g["ids"].append(oid)
        g["records"] += used_j[oid]

    used_p: Counter = Counter()
    for r in moves + payments + ml:
        p = pref(r.get("partner_id", ""))
        if p and str(p[1]) not in mapping.get("partners", {}):
            used_p[p[1]] += 1
    p_groups: dict[str, dict] = {}
    for oid in used_p:
        r = p_by_id.get(oid, {})
        key = norm_name(s(r.get("name")))
        g = p_groups.setdefault(key, {"name": s(r.get("name")), "ids": [], "refs": 0,
                                      "row": r})
        g["ids"].append(oid)
        g["refs"] += used_p[oid]

    # parent fixes
    parent_fix = []
    for r in partners_rows:
        p = pref(r.get("parent_id", ""))
        if p and str(p[1]) not in mapping.get("partners", {}):
            parent_fix.append((int(r["old_id"]), p[1]))

    # ---------------- collision sets from the target ------------------------
    tgt_account_codes = {s(r.get("code")) for r in load(NEW, "accounts") if s(r.get("code"))}
    tgt_journal_codes = {s(r.get("code")).upper() for r in load(NEW, "journals")}
    tgt_logins = {s(r.get("login")).lower() for r in load(NEW, "users")}

    # ---------------- 1. accounts -------------------------------------------
    print(f"\nACCOUNTS: {len(acc_groups)} groups, {sum(len(g['ids']) for g in acc_groups.values())} old ids")
    tgt_acc_rows = load(NEW, "accounts")
    tgt_account_codes = {s(r.get("code")) for r in tgt_acc_rows if s(r.get("code"))}
    tgt_by_type: dict[str, list[tuple[str, int, str]]] = defaultdict(list)
    for r in tgt_acc_rows:
        tgt_by_type[s(r.get("account_type"))].append(
            (norm_name(s(r.get("name"))), int(r["id"]), s(r.get("name"))))

    def fuzzy_match(name: str, atype: str) -> tuple[int, str, float] | None:
        a = set(norm_name(name).split())
        if not a:
            return None
        best = None
        for cand_key, cid, cname in tgt_by_type.get(atype, []):
            b = set(cand_key.split())
            if not b:
                continue
            score = len(a & b) / len(a | b)
            if best is None or score > best[2]:
                best = (cid, cname, score)
        return best if best and best[2] >= 0.5 else None

    def free_code(old_code: str) -> str:
        base = int(old_code)
        for delta in range(1, 500):
            cand = str(base + delta)
            if cand not in tgt_account_codes and cand not in batch_codes:
                return cand
        return ""

    batch_codes: set[str] = set()
    for g in acc_groups.values():
        if all(already("accounts", oid) for oid in g["ids"]):
            continue
        code = ""
        for oid in g["ids"]:
            c = codes.get(str(oid), {}).get("codes", {})
            if c:
                code = sorted(c.values())[0]
                break
        atype = g["types"].most_common(1)[0][0]
        if not code:
            t.skipped.append({"bucket": "accounts", "label": g["name"],
                              "reason": "no code recoverable"})
            continue
        if code in tgt_account_codes or code in batch_codes:
            fz = fuzzy_match(g["name"], atype)
            if fz:
                for oid in g["ids"]:
                    t.map["accounts"][str(oid)] = fz[0]
                t.created["accounts_fuzzy_mapped"] += 1
                t.skipped.append({"bucket": "accounts-review", "label": g["name"],
                                  "reason": f"code {code} taken in target -> mapped to "
                                            f"{fz[1]!r} (score {fz[2]:.2f}), review"})
                continue
            new_code = free_code(code)
            if not new_code:
                t.skipped.append({"bucket": "accounts", "label": g["name"],
                                  "reason": f"code {code} collides; no free code found"})
                continue
            t.create("account.account",
                     {"name": formalize(g["name"]), "code": new_code, "account_type": atype,
                      "company_ids": [(6, 0, [1])]},
                     g["name"], g["ids"], "accounts")
            t.skipped.append({"bucket": "accounts-review", "label": g["name"],
                              "reason": f"recoded {code} -> {new_code} (code already used "
                                        "in target), review"})
            batch_codes.add(new_code)
            continue
        batch_codes.add(code)
        t.create("account.account",
                 {"name": formalize(g["name"]), "code": code, "account_type": atype,
                  "company_ids": [(6, 0, [1])]},
                 g["name"], g["ids"], "accounts")
    print(f"  plan: {t.created['accounts']} created, "
          f"{t.created['accounts_fuzzy_mapped']} fuzzy-mapped, "
          f"{len([x for x in t.skipped if x['bucket']=='accounts'])} skipped")

    acc_map = {**mapping.get("accounts", {}), **t.map["accounts"]}

    def map_value(v):
        return v["new_id"] if isinstance(v, dict) else v

    acc_name_new: dict[str, int] = {}
    for oid_str, v in mapping.get("accounts", {}).items():
        r = acc_by_id.get(int(oid_str))
        if r:
            acc_name_new.setdefault(norm_name(s(r.get("name"))), map_value(v))
    for oid_str, v in t.map["accounts"].items():
        r = acc_by_id.get(int(oid_str))
        if r:
            acc_name_new.setdefault(norm_name(s(r.get("name"))), map_value(v))

    def resolve_account(old_id: int) -> int | None:
        v = acc_map.get(str(old_id))
        if v is not None:
            val = map_value(v)
            if val and val != -1:
                return val
        r = acc_by_id.get(old_id)
        if r:
            return acc_name_new.get(norm_name(s(r.get("name"))))
        return None

    # ---------------- 2. journals -------------------------------------------
    print(f"\nJOURNALS: {len(j_groups)} groups")
    j_batch_codes: set[str] = {
        s(j_by_id[int(oid)]["code"]).upper() for oid in t.map["journals"]
        if oid.isdigit() and int(oid) in j_by_id and t.map["journals"][oid] != -1}
    for g in j_groups.values():
        if any(already("journals", oid) for oid in g["ids"]):
            continue
        code = g["code"]
        if code.upper() in tgt_journal_codes or code.upper() in j_batch_codes:
            alt = ""
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                cand = code + letter
                if cand.upper() not in tgt_journal_codes and cand.upper() not in j_batch_codes:
                    alt = cand
                    break
            if not alt:
                t.skipped.append({"bucket": "journals", "label": f"{code} {g['name']}",
                                  "reason": f"code {code} already used; no free variant"})
                continue
            t.skipped.append({"bucket": "journals-review", "label": f"{code} {g['name']}",
                              "reason": f"recoded {code} -> {alt} (code already used), review"})
            code = alt
        j_batch_codes.add(code.upper())
        vals = {"name": formalize(g["name"]), "code": code, "type": g["type"],
                "company_id": 1}
        if g["type"] in ("bank", "cash"):
            def_acc = None
            for oid in g["ids"]:
                p = pref(j_by_id.get(oid, {}).get("default_account_id", ""))
                if p:
                    def_acc = resolve_account(p[1])
                    if def_acc:
                        break
            if def_acc:
                vals["default_account_id"] = def_acc
            else:
                t.skipped.append({"bucket": "journals",
                                  "label": f"{g['code']} {g['name']}",
                                  "reason": "bank/cash journal without resolvable default account"})
                continue
        t.create("account.journal", vals, f"{g['code']} {g['name']}", g["ids"], "journals")
    print(f"  plan: {t.created['journals']} created, {len([x for x in t.skipped if x['bucket']=='journals'])} skipped")

    # ---------------- 3. partners -------------------------------------------
    # include parents only when a MIGRATED child needs the link
    for child_oid, parent_oid in parent_fix:
        if not (already("partners", child_oid)
                or str(child_oid) in mapping.get("partners", {})):
            continue
        if str(parent_oid) in mapping.get("partners", {}) or already("partners", parent_oid):
            continue
        r = p_by_id.get(parent_oid)
        if not r:
            continue
        key = norm_name(s(r.get("name")))
        g = p_groups.setdefault(key, {"name": s(r.get("name")), "ids": [],
                                      "refs": 0, "row": r})
        if parent_oid not in g["ids"]:
            g["ids"].append(parent_oid)
    print(f"\nPARTNERS: {len(p_groups)} groups")
    cust_ids = {pref(r.get('partner_id',''))[1] for r in moves
                if r.get('move_type') == 'out_invoice' and pref(r.get('partner_id',''))}
    sup_ids = {pref(r.get('partner_id',''))[1] for r in moves
               if r.get('move_type') == 'in_invoice' and pref(r.get('partner_id',''))}
    for g in p_groups.values():
        if any(already("partners", oid) for oid in g["ids"]):
            continue
        r = g["row"]
        vals = {"name": formalize(g["name"]), "is_company": s(r.get("is_company")).lower() == "true"}
        for field, key in (("email", "email"), ("phone", "phone")):
            if s(r.get(key)):
                vals[field] = s(r.get(key))
        p = pref(r.get("country_id", ""))
        if p and str(p[1]) in mapping.get("countries", {}):
            vals["country_id"] = mapping["countries"][str(p[1])]["new_id"]
        if any(oid in cust_ids for oid in g["ids"]):
            vals["customer_rank"] = 1
        if any(oid in sup_ids for oid in g["ids"]):
            vals["supplier_rank"] = 1
        t.create("res.partner", vals, g["name"], g["ids"], "partners")
    print(f"  plan: {t.created['partners']} created, {len([x for x in t.skipped if x['bucket']=='partners'])} skipped")

    # ---------------- 4. users (inactive) -----------------------------------
    umap = mapping.get("users", {})
    user_ids = [int(r["old_id"]) for r in users_rows if str(r["old_id"]) not in umap]
    print(f"\nUSERS: {len(user_ids)} to create inactive")
    for r in users_rows:
        oid = int(r["old_id"])
        if str(oid) in umap or already("users", oid):
            continue
        login = s(r.get("login"))
        if login.lower() in tgt_logins:
            t.skipped.append({"bucket": "users", "label": f"{login}",
                              "reason": "login already exists in target"})
            continue
        vals = {"name": formalize(s(r.get("name"))), "login": login, "email": login}
        if not t.apply:
            t.map["users"][str(oid)] = -1
            t.created["users"] += 1
            continue
        try:
            new_id = t.kw("res.users", "create", [vals])
            t.kw("res.users", "write", [[new_id], {"active": False}])
        except SystemExit as exc:
            t.skipped.append({"bucket": "users", "label": login,
                              "reason": str(exc)[:160]})
            continue
        t.map["users"][str(oid)] = int(new_id)
        t.created["users"] += 1
    print(f"  plan: {t.created['users']} created, {len([x for x in t.skipped if x['bucket']=='users'])} skipped")

    # ---------------- 5. partner parent fixes -------------------------------
    print(f"\nPARENT FIXES: {len(parent_fix)}")
    for child_oid, parent_oid in parent_fix:
        new_child = t.map["partners"].get(str(child_oid)) or \
            (mapping.get("partners", {}).get(str(child_oid)) or {}).get("new_id")
        if not new_child:
            continue  # child contact is not part of the migration; no link needed
        new_parent = t.map["partners"].get(str(parent_oid)) or \
            (mapping.get("partners", {}).get(str(parent_oid)) or {}).get("new_id")
        if new_parent and new_child != -1:
            if t.apply:
                try:
                    t.kw("res.partner", "write", [[new_child], {"parent_id": new_parent}])
                except SystemExit as exc:
                    t.skipped.append({"bucket": "parents", "label": str(child_oid),
                                      "reason": str(exc)[:120]})
            t.created["parents"] += 1
        else:
            t.skipped.append({"bucket": "parents", "label": f"{child_oid}->{parent_oid}",
                              "reason": "parent not resolvable after creation"})

    # ---------------- output -------------------------------------------------
    report = {"db": args.db, "apply": t.apply, "created": dict(t.created),
              "skipped": t.skipped, "map": t.map}
    Path(args.map_out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\ncreated: {dict(t.created)}")
    print(f"skipped: {len(t.skipped)}")
    for x in t.skipped[:12]:
        print(f"   - [{x['bucket']}] {x['label'][:40]}: {x['reason'][:90]}")
    print(f"-> {Path(args.map_out).name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
