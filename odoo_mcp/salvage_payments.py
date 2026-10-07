"""Adopt payments that exist in the target but are missing from the import state
(created by an interrupted run). Matches to source by 'Old Name: <name>' in the
memo, posts drafts, restores the unit link, records in the state file.
Usage: python salvage_payments.py [--db sgc_mt_parkgroup]
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from sgc_target_read import load_creds, rpc  # noqa: E402


def oid(s):
    m = re.search(r"\((\d+)\)\s*$", str(s) or "")
    return int(m.group(1)) if m else None


def fl(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sgc_mt_parkgroup")
    args = ap.parse_args()
    creds = load_creds()
    rid = [1]

    def kw(model, meth, a, kwargs=None):
        try:
            return rpc(creds["ODOO_URL"], "object", "execute_kw",
                       [args.db, 2, creds["ODOO_API_KEY"], model, meth, a, kwargs or {}], rid)
        except SystemExit as e:
            raise RuntimeError(str(e)) from None

    state_path = ROOT / f"import_map_{args.db}.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    mapping = json.loads((ROOT / "target_mapping_2026-10-06.json").read_text(encoding="utf-8"))
    byname = {}
    for r in csv.DictReader((ROOT / "migration_out/payments.csv").open(encoding="utf-8-sig")):
        byname.setdefault(r["name"], []).append(r)
    known = set(state["maps"].get("payments", {}).values())
    pays = kw("account.payment", "search_read", [[["memo", "like", "[%"]]],
              {"fields": ["id", "name", "memo", "amount", "state", "move_id"]})
    orphans = [p for p in pays if p["id"] not in known]
    print(f"payments with tag {len(pays)} | unrecorded {len(orphans)}")
    adopted, skipped = {}, []
    maps = state.setdefault("maps", {}).setdefault("payments", {})
    dups = state.setdefault("payment_dups", [])
    dup_ids = {d["dup_id"] for d in dups}
    for p in orphans:
        if p["id"] in dup_ids:
            continue
        m = re.search(r"Old Name:\s*(\S+)", p["memo"] or "")
        cands = byname.get(m.group(1), []) if m else []
        cands = [c for c in cands if abs(fl(c["amount"]) - fl(p["amount"])) <= 0.02]
        if len(cands) != 1:
            skipped.append((p["id"], p["name"], m.group(1) if m else "?"))
            continue
        old = int(cands[0]["old_id"])
        if str(old) in maps:
            dups.append({"old": old, "dup_id": p["id"], "name": p["name"], "state": p["state"]})
            dup_ids.add(p["id"])
            continue
        adopted[p["id"]] = (old, cands[0])
    print(f"matched {len(adopted)} | duplicates {len(dups)} | skipped {len(skipped)}: {skipped[:5]}")
    drafts = [p for p in orphans if p["id"] in adopted and p["state"] == "draft"]
    if drafts:
        try:
            kw("account.payment", "action_post", [[p["id"] for p in drafts]])
        except Exception:  # noqa: BLE001
            for p in drafts:
                try:
                    kw("account.payment", "action_post", [[p["id"]]])
                except Exception as e:  # noqa: BLE001
                    print("   post failing:", p["id"], str(e)[:90])
    back = {p["id"]: p for p in kw("account.payment", "read", [[i for i in adopted]],
                                   {"fields": ["name", "amount", "state", "move_id"]})}
    for pid, (old, r) in adopted.items():
        p = back[pid]
        flags = [] if p["state"] in ("paid", "in_process", "posted") else [f"state={p['state']}"]
        state["maps"].setdefault("payments", {})[str(old)] = pid
        state["verified"].setdefault("payments", {})[str(old)] = flags or ["ok (salvaged payment)"]
        if flags:
            state["errors"].append({"dataset": "payments", "old_id": old, "new_id": pid,
                                    "flags": ["salvage: " + "; ".join(flags)]})
        u = oid(r.get("property_id"))
        unit = mapping.get("units", {}).get(str(u)) if u else None
        if unit and p.get("move_id"):
            try:
                kw("account.move", "write", [[p["move_id"][0]], {"sold_property_id": unit["new_id"]}])
            except Exception:  # noqa: BLE001
                pass
    state_path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    print("state payments:", len(state["maps"].get("payments", {})))


if __name__ == "__main__":
    main()
