"""Adopt moves that exist in the target but are missing from the import state
(created by an interrupted run). Matches each orphan to its source row by
name + amount + company tag, posts drafts, records it in the state file.
Usage: python salvage_orphans.py [--db sgc_mt_rehearsal]
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


TAGCO = {"PHI": "PARK HOMES INTERNATIONAL", "PGI": "PARK GROUP INVESTMENT",
         "PRED": "PARK REAL ESTATE DEVELOPMENT", "PBR": "PBR REAL ESTATE DEVELOPMENT",
         "AIWA": "AIWA", "PRES": "PARK RESIDENCY", "PINV": "PARK I N V"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sgc_mt_rehearsal")
    args = ap.parse_args()
    creds = load_creds()
    rid = [1]

    def kw(model, meth, args_, kwargs=None):
        try:
            return rpc(creds["ODOO_URL"], "object", "execute_kw",
                       [args.db, 2, creds["ODOO_API_KEY"], model, meth, args_, kwargs or {}], rid)
        except SystemExit as e:
            raise RuntimeError(str(e)) from None

    state_path = ROOT / f"import_map_{args.db}.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    known = {v for m in state["maps"].values() for v in m.values()}
    paymoves = {oid(p["move_id"]) for p in
                csv.DictReader((ROOT / "migration_out/payments.csv").open(encoding="utf-8-sig"))}
    paymoves.discard(None)

    src = {"invoices": [], "bills": [], "journal_entries": []}
    for ds in src:
        for r in csv.DictReader((ROOT / f"migration_out/{ds}.csv").open(encoding="utf-8-sig")):
            o = int(r["old_id"])
            if o in paymoves:
                continue
            src[ds].append(r)

    mv = kw("account.move", "search_read", [[["ref", "like", "[%]"], ["state", "in", ["draft", "posted"]]]],
            {"fields": ["id", "name", "ref", "state", "amount_total"]})
    orphans = [m for m in mv if m["id"] not in known and not str(m["name"]).startswith("PBNK")]
    print(f"tagged moves {len(mv)} | unrecorded orphans {len(orphans)}")
    adopted, skipped = {}, []
    for m in orphans:
        tag_m = re.search(r"\[(\w+)\]", m["ref"] or "")
        tag = tag_m.group(1) if tag_m else "?"
        comp = TAGCO.get(tag, "")
        base = re.sub(r"\s*\[[A-Z]+\]$", "", m["name"] or "")
        cands = []
        for ds, rows in src.items():
            for r in rows:
                if r["name"] == base and abs(fl(r["amount_total"]) - m["amount_total"]) <= 0.02 \
                        and comp in r["company_id"]:
                    cands.append((ds, r))
        if len(cands) != 1:
            skipped.append((m["id"], m["name"], f"candidates={len(cands)}"))
            continue
        ds, r = cands[0]
        adopted[m["id"]] = (ds, int(r["old_id"]), r)
    print(f"matched {len(adopted)} | skipped {len(skipped)}: {skipped[:6]}")
    drafts = [m for m in orphans if m["id"] in adopted and m["state"] == "draft"]
    if drafts:
        try:
            kw("account.move", "action_post", [[m["id"] for m in drafts]])
        except Exception:  # noqa: BLE001
            for m in drafts:
                try:
                    kw("account.move", "action_post", [[m["id"]]])
                except Exception as e:  # noqa: BLE001
                    print("   post still failing:", m["id"], str(e)[:100])
    back = {x["id"]: x for x in kw("account.move", "read", [[i for i in adopted]],
                                   {"fields": ["name", "state", "amount_total"]})}
    for mid, (ds, old, r) in adopted.items():
        m = back[mid]
        flags = []
        if m["state"] != "posted":
            flags.append(f"state={m['state']}")
        if abs(fl(m["amount_total"]) - fl(r["amount_total"])) > 0.02:
            flags.append(f"total {m['amount_total']} != {r['amount_total']}")
        state["maps"].setdefault(ds, {})[str(old)] = mid
        state["verified"].setdefault(ds, {})[str(old)] = flags or ["ok (salvaged)"]
        if flags:
            state["errors"].append({"dataset": ds, "old_id": old, "new_id": mid,
                                    "flags": ["salvage: " + "; ".join(flags)]})
        print("  ", ds, old, "->", mid, m["name"], m["state"], m["amount_total"])
    state_path.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    print("state maps:", {k: len(v) for k, v in state["maps"].items()})


if __name__ == "__main__":
    main()
