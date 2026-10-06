"""Post-import verification: compare rehearsal DB against source CSVs.
Checks per dataset: record counts, amount totals, per-account debit/credit sums,
entity-tag coverage, unit links. Read-only.
"""
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from sgc_target_read import load_creds, rpc  # noqa: E402

DB = sys.argv[1] if len(sys.argv) > 1 else "sgc_mt_rehearsal"
creds = load_creds()
rid = [1]


def kw(model, meth, args, kwargs=None):
    try:
        return rpc(creds["ODOO_URL"], "object", "execute_kw",
                   [DB, 2, creds["ODOO_API_KEY"], model, meth, args, kwargs or {}], rid)
    except SystemExit as e:
        raise RuntimeError(str(e)) from None


def oid(s):
    m = re.search(r"\((\d+)\)\s*$", str(s) or "")
    return int(m.group(1)) if m else None


def fl(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def load(name):
    p = ROOT / "migration_out" / f"{name}.csv"
    with p.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


state = json.loads((ROOT / f"import_map_{DB}.json").read_text(encoding="utf-8"))
mapping = json.loads((ROOT / "target_mapping_2026-10-06.json").read_text(encoding="utf-8"))
readiness = json.loads((ROOT / "readiness_2026-10-06.json").read_text(encoding="utf-8"))

# expected source sets
paymoves = {oid(p["move_id"]) for p in load("payments")}
paymoves.discard(None)
exp = {"out_invoice": (0, 0.0), "in_invoice": (0, 0.0), "entry": (0, 0.0)}
exp_moves = set()
for ds in ["invoices", "bills", "journal_entries"]:
    skip = {int(k) for k in readiness["skip"].get(ds, {})}
    hold = {int(k) for k in readiness["hold"].get(ds, {})}
    for r in load(ds):
        o = int(r["old_id"])
        if o in skip or o in hold:
            continue
        if ds == "journal_entries" and o in paymoves:
            continue
        n, s = exp[r["move_type"]]
        exp[r["move_type"]] = (n + 1, s + fl(r["amount_total"]))
        exp_moves.add(o)
print("expected moves:", {k: (v[0], round(v[1], 2)) for k, v in exp.items()})

# target
rows = kw("account.move", "read_group", [[["ref", "like", "[%]"], ["state", "=", "posted"]],
                                         ["amount_total"], ["move_type"]])
got = {r["move_type"]: (r["move_type_count"], r["amount_total"]) for r in rows}
print("target moves:  ", {k: (v[0], round(v[1], 2)) for k, v in got.items()})
ok = True
for mt, (n, s) in exp.items():
    gn, gs = got.get(mt, (0, 0.0))
    if gn != n or abs(gs - s) > 1.0:
        ok = False
        print(f"  MISMATCH {mt}: count {gn} vs {n} | sum {gs:.2f} vs {s:.2f}")

# entity tags
tagdrafts = kw("account.move", "search_count", [[["ref", "like", "[%]"], ["narration", "not like", "Legacy Entity:"]]])
print("moves with tag but missing narration:", tagdrafts)

# unit links
units = mapping.get("units", {})
exp_units, exp_pay_units = 0, 0
for ds in ["invoices", "bills", "journal_entries"]:
    skip = {int(k) for k in readiness["skip"].get(ds, {})}
    hold = {int(k) for k in readiness["hold"].get(ds, {})}
    for r in load(ds):
        o = int(r["old_id"])
        if o in skip or o in hold or (ds == "journal_entries" and o in paymoves):
            continue
        if oid(r.get("property_id")) and str(oid(r["property_id"])) in units:
            exp_units += 1
pskip = {int(k) for k in readiness["skip"].get("payments", {})}
phold = {int(k) for k in readiness["hold"].get("payments", {})}
for r in load("payments"):
    o = int(r["old_id"])
    if o in pskip or o in phold or r.get("state") == "canceled":
        continue
    if oid(r.get("property_id")) and str(oid(r["property_id"])) in units:
        exp_pay_units += 1
got_units = kw("account.move", "search_count", [[["ref", "like", "[%]"], ["sold_property_id", "!=", False]]])
print(f"unit links: moves expected {exp_units + exp_pay_units} (incl. payment moves {exp_pay_units}) | set on target {got_units}")

# per-account totals
src_acc = defaultdict(lambda: [0.0, 0.0])
for ln in load("move_lines"):
    o = oid(ln["move_id"])
    if o not in exp_moves:
        continue
    acc = mapping["accounts"].get(str(oid(ln["account_id"])))
    if isinstance(acc, dict):
        acc = acc.get("new_id")
    if not acc:
        acc = state["maps"].get("accounts", {})
    if not isinstance(acc, int):
        acc = None
    if not acc:
        continue
    src_acc[acc][0] += fl(ln["debit"])
    src_acc[acc][1] += fl(ln["credit"])
rows = kw("account.move.line", "read_group",
          [[["move_id.ref", "like", "[%]"], ["move_id.state", "=", "posted"]],
           ["debit", "credit"], ["account_id"]])
tgt_acc = {r["account_id"][0]: [r["debit"], r["credit"]] for r in rows if r["account_id"]}
bad = []
for acc, (d, c) in src_acc.items():
    td, tc = tgt_acc.get(acc, [0.0, 0.0])
    if abs(d - td) > 1.0 or abs(c - tc) > 1.0:
        bad.append((acc, d, td, c, tc))
print(f"accounts compared: {len(src_acc)} | accounts with >1 AED variance: {len(bad)}")
for acc, d, td, c, tc in sorted(bad, key=lambda x: -abs(x[1] - x[2]))[:15]:
    print(f"   acc {acc}: debit {d:.2f} vs {td:.2f} | credit {c:.2f} vs {tc:.2f}")

# payments
exp_pn, exp_ps = 0, 0.0
for r in load("payments"):
    o = int(r["old_id"])
    if o in pskip or o in phold or r.get("state") == "canceled":
        continue
    exp_pn += 1
    exp_ps += fl(r["amount"])
rows = kw("account.payment", "read_group", [[["memo", "like", "[%]"], ["state", "in", ["paid", "in_process"]]],
                                            ["amount"], []])
pn = rows[0]["__count"] if rows else 0
ps = rows[0]["amount"] if rows else 0.0
print(f"payments: expected {exp_pn} sum {exp_ps:.2f} | target {pn} sum {ps:.2f} {'OK' if pn == exp_pn and abs(ps - exp_ps) < 1.0 else 'MISMATCH'}")

print("errors in import state:", len(state.get("errors", [])))
print("VERDICT:", "PASS" if ok and not bad else "REVIEW NEEDED")
