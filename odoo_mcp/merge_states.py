"""Merge parallel import state files into the main state file for a db.
Usage: python merge_states.py --db sgc_mt_parkgroup --extra import_map_prod_je.json import_map_prod_pay.json
"""
import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="sgc_mt_parkgroup")
    ap.add_argument("--extra", nargs="+", required=True)
    args = ap.parse_args()
    main_path = ROOT / f"import_map_{args.db}.json"
    main = json.loads(main_path.read_text(encoding="utf-8"))
    for name in args.extra:
        p = ROOT / name
        if not p.exists():
            print("missing:", name)
            continue
        extra = json.loads(p.read_text(encoding="utf-8"))
        for kind, m in extra.get("maps", {}).items():
            tgt = main["maps"].setdefault(kind, {})
            added = 0
            for k, v in m.items():
                if k not in tgt:
                    tgt[k] = v
                    added += 1
            print(f"{name}: {kind} +{added} (total {len(tgt)})")
        for kind, m in extra.get("verified", {}).items():
            tgt = main["verified"].setdefault(kind, {})
            for k, v in m.items():
                tgt.setdefault(k, v)
        for kind, m in extra.get("renamed", {}).items():
            tgt = main.setdefault("renamed", {}).setdefault(kind, {})
            for k, v in m.items():
                tgt.setdefault(k, v)
        main["errors"].extend(e for e in extra.get("errors", []))
        for k, v in extra.get("void", {}).items():
            main.setdefault("void", {})[k] = v
    # dedupe identical error dicts
    seen = set()
    uniq = []
    for e in main["errors"]:
        key = json.dumps(e, sort_keys=True)
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    main["errors"] = uniq
    main_path.write_text(json.dumps(main, indent=1, ensure_ascii=False), encoding="utf-8")
    print("merged ->", main_path.name)
    print("maps:", {k: len(v) for k, v in main["maps"].items()})
    print("errors:", len(main["errors"]))


if __name__ == "__main__":
    main()
