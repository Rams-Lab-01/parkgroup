"""Normalize the formal text style (no ALL-CAPS / all-lowercase) on records
already imported into the target DB. Idempotent; only writes changed values.
Targets: account.move (ref, narration), account.move.line (name),
account.payment (memo), created res.partner / res.users / account.account /
account.journal names (from the creation map).
Usage: python normalize_text.py [--db sgc_mt_rehearsal] [--creation creation_map_rehearsal.json]
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from sgc_target_read import load_creds, rpc  # noqa: E402
from import_moves import formalize  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sgc_mt_rehearsal")
    ap.add_argument("--creation", default="creation_map_rehearsal.json")
    args = ap.parse_args()
    creds = load_creds()
    rid = [1]

    def kw(model, meth, a, kwargs=None):
        try:
            return rpc(creds["ODOO_URL"], "object", "execute_kw",
                       [args.db, 2, creds["ODOO_API_KEY"], model, meth, a, kwargs or {}], rid)
        except SystemExit as e:
            raise RuntimeError(str(e)) from None

    t0 = time.time()
    stats = {}

    def flush(model, field, changes):
        groups = defaultdict(list)
        for i, v in changes:
            groups[v].append(i)
        n = 0
        for val, ids in groups.items():
            for k in range(0, len(ids), 300):
                kw(model, "write", [ids[k:k + 300], {field: val}])
                n += len(ids[k:k + 300])
        return n

    ids = []
    off = 0
    while True:
        page = kw("account.move", "search_read", [[["ref", "like", "[%]"]]],
                  {"fields": ["id", "ref", "narration"], "limit": 1000, "offset": off, "order": "id"})
        if not page:
            break
        off += len(page)
        for m in page:
            nr = formalize(m["ref"])
            nn = formalize(m["narration"])
            if nr != m["ref"] or nn != (m["narration"] or ""):
                ids.append((m["id"], nr, nn, m["ref"], m["narration"]))
    groups = defaultdict(list)
    for i, nr, nn, _a, _b in ids:
        groups[(nr, nn)].append(i)
    n = 0
    for (nr, nn), gid in groups.items():
        for k in range(0, len(gid), 300):
            kw("account.move", "write", [gid[k:k + 300], {"ref": nr, "narration": nn}])
            n += len(gid[k:k + 300])
    stats["moves ref+narration"] = n

    lines = []
    off = 0
    while True:
        page = kw("account.move.line", "search_read", [[["move_id.ref", "like", "[%]"]]],
                  {"fields": ["id", "name"], "limit": 2000, "offset": off, "order": "id"})
        if not page:
            break
        off += len(page)
        for l in page:
            nn = formalize(l["name"])
            if nn != l["name"]:
                lines.append((l["id"], nn))
    stats["move line names"] = flush("account.move.line", "name", lines)

    pays = []
    off = 0
    while True:
        page = kw("account.payment", "search_read", [[["memo", "like", "[%"]]],
                  {"fields": ["id", "memo"], "limit": 1000, "offset": off, "order": "id"})
        if not page:
            break
        off += len(page)
        for p in page:
            nn = formalize(p["memo"])
            if nn != p["memo"]:
                pays.append((p["id"], nn))
    stats["payment memos"] = flush("account.payment", "memo", pays)

    creation = json.loads((ROOT / args.creation).read_text(encoding="utf-8"))
    cm = creation["map"]
    for model, kind in (("res.partner", "partners"), ("res.users", "users"),
                        ("account.account", "accounts"), ("account.journal", "journals")):
        new_ids = [v for v in cm.get(kind, {}).values() if isinstance(v, int) and v > 0]
        if not new_ids:
            continue
        changes = []
        for k in range(0, len(new_ids), 300):
            for r in kw(model, "read", [new_ids[k:k + 300]], {"fields": ["id", "name"]}):
                nn = formalize(r.get("name"))
                if nn != r.get("name"):
                    changes.append((r["id"], nn))
        stats[f"{model} names"] = flush(model, "name", changes)

    print(f"normalized in {time.time() - t0:.0f}s:")
    for k, v in stats.items():
        print(f"   {k}: {v} changed")


if __name__ == "__main__":
    main()
