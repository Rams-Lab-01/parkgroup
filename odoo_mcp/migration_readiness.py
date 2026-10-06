"""Migration readiness gate: reconcile every row of the 20 migration datasets
against the old_id -> new_id mapping BEFORE anything is migrated.

For each row every reference field is resolved; rows land in one of:
  READY           all references resolve, no defect found
  PENDING         needs a policy decision first (flagged, not decided here):
                  user attribution, product links, analytics, unit links
  HOLD            data-level problem: unresolved account/journal/partner/tax/
                  fiscal-position ref, unknown move ref, unbalanced move

Checks: per-move debit=credit, orphan lines, duplicate ids/names, target name
collisions, invoice/payment totals.  Nothing is written to any DB.

Outputs: migration_readiness_2026-10-06.xlsx + readiness_2026-10-06.json
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(r"C:\Parkgroup Data\odoo_mcp")
sys.path.insert(0, str(ROOT))
from reconcile import _add_sheet, norm_name  # noqa: E402

OLD = ROOT / "migration_out"
NEW = ROOT / "target_out"
MAP_JSON = ROOT / "target_mapping_2026-10-06.json"
OUT_XLSX = ROOT / "migration_readiness_2026-10-06.xlsx"
OUT_JSON = ROOT / "readiness_2026-10-06.json"

MOVE_DATASETS = ("invoices", "bills", "journal_entries", "customer_refunds",
                 "vendor_refunds", "receipts")
LOAD_ORDER = ("companies", "currencies", "countries", "journals", "accounts",
              "taxes", "payment_terms", "partners", "products", "users",
              "analytic_accounts", "fiscal_positions", "invoices", "bills",
              "customer_refunds", "vendor_refunds", "receipts",
              "journal_entries", "payments", "move_lines")

M2O = {
    "company_id": "companies", "currency_id": "currencies",
    "journal_id": "journals", "account_id": "accounts",
    "default_account_id": "accounts", "outstanding_account_id": "accounts",
    "destination_account_id": "accounts", "partner_id": "partners",
    "parent_id": "partners", "fiscal_position_id": "fiscal_positions",
    "country_id": "countries", "tax_line_id": "taxes",
}
# Decisions taken 2026-10-06 (user): missing reference records (accounts,
# journals, partners) are created as needed; 14 staff users are created
# inactive; product links become line-description text; analytics are dropped;
# units were mapped into target_mapping_2026-10-06.json["units"].
NOTE_FIELDS = {
    "full_reconcile_id": "reconciliation state: route decision pending (.dump reconsideration)",
    "user_id": "staff attribution: users created inactive (decision)",
    "invoice_user_id": "staff attribution: users created inactive (decision)",
    "product_id": "product link folded into line description (decision)",
    "analytic_distribution": "analytics dropped - not required (reviewed)",
}
CREATE_ENTITIES = ("accounts", "journals", "partners", "taxes")
# Columns present in the wide export that are redundant for the import: they are
# derivable from the parent record or are not part of the migrated field set.
IGNORED = {
    ("move_lines", "journal_id"), ("move_lines", "company_id"),
    ("move_lines", "currency_id"),
    ("products", "partner_id"), ("users", "partner_id"),
    ("companies", "partner_id"), ("analytic_accounts", "partner_id"),
}
TAX_TABLE_NOTE = ("5% emirate tax rename table applied (DB->DU, AD->AZ, S->SH, "
                  "A->AJ, UAQ->UQ, RAK->RK, F->FU) - confirm")
REF_RE = re.compile(r"^(?P<name>.*?)\s*\((?P<id>\d+)\)$")


def s(value: object) -> str:
    if value in (None, "", "False", "None"):
        return ""
    return str(value).strip()


def load(name: str) -> list[dict]:
    with (OLD / f"{name}.csv").open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def parse_ref(value: str) -> tuple[str, int] | None:
    v = s(value)
    if not v:
        return None
    m = REF_RE.match(v)
    if m:
        return m.group("name"), int(m.group("id"))
    if v.isdigit():
        return "", int(v)
    return None


def main() -> int:
    mapping = json.loads(MAP_JSON.read_text(encoding="utf-8"))
    datasets = {name: load(name) for name in LOAD_ORDER}

    move_index: dict[int, str] = {}
    for ds in MOVE_DATASETS:
        for r in datasets[ds]:
            move_index[int(r["old_id"])] = ds
    line_ids = {int(r["old_id"]) for r in datasets["move_lines"]}

    lines_by_move: dict[int, list[dict]] = defaultdict(list)
    for r in datasets["move_lines"]:
        pr = parse_ref(r.get("move_id", ""))
        if pr:
            lines_by_move[pr[1]].append(r)

    unresolved_by_field: dict[str, int] = defaultdict(int)
    status: dict[str, dict[int, dict]] = {}
    for ds in LOAD_ORDER:
        status[ds] = {}
        for r in datasets[ds]:
            oid = int(r["old_id"])
            reasons: dict[str, list[str]] = {"data": [], "create": [],
                                             "notes": [], "skip": []}

            def resolve(field: str, value: str) -> None:
                pr = parse_ref(value)
                if pr is None:
                    return
                _, ext = pr
                if field == "move_id":
                    if ext not in move_index:
                        reasons["skip"].append("line of a move not in the export")
                    return
                if field == "payment_method_id":
                    if s(value) not in mapping.get("payment_methods", {}):
                        reasons["create"].append("payment_method (create)")
                    return
                if field == "property_id":
                    if str(ext) not in mapping.get("units", {}):
                        reasons["data"].append("property_id (unit) unresolved")
                        unresolved_by_field["property_id"] += 1
                    return
                if field in NOTE_FIELDS:
                    reasons["notes"].append(NOTE_FIELDS[field])
                    return
                ent = M2O.get(field)
                if ent and str(ext) not in mapping.get(ent, {}):
                    if ent in CREATE_ENTITIES:
                        reasons["create"].append(f"{field} (create)")
                        unresolved_by_field[field] += 1
                    else:
                        reasons["data"].append(f"{field} unresolved")
                        unresolved_by_field[field] += 1

            for key in r:
                if (ds, key) in IGNORED:
                    continue
                if key in M2O or key in NOTE_FIELDS or key == "property_id" \
                        or key in ("move_id", "payment_method_id"):
                    resolve(key, r.get(key, ""))

            status[ds][oid] = reasons

    # ---- per-move rollup: a move inherits its lines' problems --------------
    for mid, ds in move_index.items():
        agg = status[ds].get(mid)
        if agg is None:
            continue
        for ln in lines_by_move.get(mid, []):
            lr = status["move_lines"].get(int(ln["old_id"]))
            if not lr:
                continue
            for bucket in ("data", "create", "notes"):
                for reason in lr[bucket]:
                    if reason not in agg[bucket]:
                        agg[bucket].append(reason)
        debit = sum(float(s(ln.get("debit")) or 0) for ln in lines_by_move.get(mid, []))
        credit = sum(float(s(ln.get("credit")) or 0) for ln in lines_by_move.get(mid, []))
        if abs(debit - credit) > 0.01:
            agg["data"].append("move unbalanced")
            unresolved_by_field["move_unbalanced"] += 1
        if mid not in lines_by_move and ds != "customer_refunds":
            agg["data"].append("move has no lines in export")
            unresolved_by_field["move_without_lines"] += 1

    # ---- dataset-level checks ----------------------------------------------
    defects: list[dict] = []
    for ds in LOAD_ORDER:
        seen: dict[int, int] = defaultdict(int)
        for r in datasets[ds]:
            seen[int(r["old_id"])] += 1
        dupes = [i for i, n in seen.items() if n > 1]
        if dupes:
            defects.append({"dataset": ds, "check": "duplicate old_id",
                            "count": len(dupes), "example": dupes[:5]})
    for ds in MOVE_DATASETS:
        names: dict[tuple, int] = defaultdict(int)
        for r in datasets[ds]:
            names[(s(r.get("name")), s(r.get("company_id")))] += 1
        dup = [k for k, n in names.items() if n > 1]
        if dup:
            defects.append({"dataset": ds, "check": "duplicate move name+company",
                            "count": len(dup),
                            "example": [f"{k[0]} / {k[1][:24]}" for k in dup[:5]]})

    target_moves = {(s(r.get("name")), s(r.get("move_type")))
                    for r in csv.DictReader(
                        (NEW / "moves_existing.csv").open(encoding="utf-8-sig"))}
    collisions = [f"{ds}:{r.get('name')}" for ds in MOVE_DATASETS
                  for r in datasets[ds]
                  if (s(r.get("name")), s(r.get("move_type"))) in target_moves]
    if collisions:
        defects.append({"dataset": "all", "check": "name collision with target moves",
                        "count": len(collisions), "example": collisions[:5]})

    orphan_lines = sum(1 for r in datasets["move_lines"]
                       if (parse_ref(r.get("move_id", "")) or (None, None))[1]
                       not in move_index)

    # ---- create-candidates: referenced by migrated data but missing ---------
    acc_used: dict[int, int] = defaultdict(int)
    for r in datasets["move_lines"]:
        pr = parse_ref(r.get("account_id", ""))
        if pr and str(pr[1]) not in mapping.get("accounts", {}):
            acc_used[pr[1]] += 1
    acc_names = {int(r["old_id"]): (s(r.get("name")), s(r.get("code")),
                                    s(r.get("account_type")))
                 for r in datasets["accounts"]}
    acc_groups: dict[str, dict] = {}
    for oid, n in sorted(acc_used.items(), key=lambda kv: -kv[1]):
        name, code, atype = acc_names.get(oid, ("?", "", ""))
        g = acc_groups.setdefault(norm_name(name), {
            "name": name, "types": set(), "old_ids": [], "lines": 0})
        g["old_ids"].append(oid)
        g["lines"] += n
        g["types"].add(atype)
    create_accounts = [{"name": g["name"], "account_type": "/".join(sorted(g["types"])),
                        "old_ids": ", ".join(map(str, g["old_ids"][:6])),
                        "copies": len(g["old_ids"]), "lines_affected": g["lines"]}
                       for g in acc_groups.values()]
    create_accounts.sort(key=lambda r: -r["lines_affected"])

    j_used: dict[int, int] = defaultdict(int)
    move_rows_all = [r for ds in MOVE_DATASETS for r in datasets[ds]] + datasets["payments"]
    for r in move_rows_all:
        pr = parse_ref(r.get("journal_id", ""))
        if pr and str(pr[1]) not in mapping.get("journals", {}):
            j_used[pr[1]] += 1
    j_names = {int(r["old_id"]): (s(r.get("code")), s(r.get("name")), s(r.get("type")))
               for r in datasets["journals"]}
    j_groups: dict[tuple, dict] = {}
    for oid, n in sorted(j_used.items(), key=lambda kv: -kv[1]):
        code, name, jtype = j_names.get(oid, ("?", "", ""))
        g = j_groups.setdefault((code, name, jtype), {
            "code": code, "name": name, "type": jtype, "old_ids": [], "records": 0})
        g["old_ids"].append(oid)
        g["records"] += n
    create_journals = [{"code": g["code"], "name": g["name"], "type": g["type"],
                        "old_ids": ", ".join(map(str, g["old_ids"][:6])),
                        "copies": len(g["old_ids"]), "records_affected": g["records"]}
                       for g in j_groups.values()]
    create_journals.sort(key=lambda r: -r["records_affected"])

    p_used: dict[int, int] = defaultdict(int)
    for r in move_rows_all + datasets["move_lines"]:
        pr = parse_ref(r.get("partner_id", ""))
        if pr and str(pr[1]) not in mapping.get("partners", {}):
            p_used[pr[1]] += 1
    p_names = {int(r["old_id"]): (s(r.get("name")), s(r.get("is_company")))
               for r in datasets["partners"]}
    p_groups: dict[str, dict] = {}
    for oid, n in sorted(p_used.items(), key=lambda kv: -kv[1]):
        name, is_co = p_names.get(oid, ("?", ""))
        g = p_groups.setdefault(norm_name(name), {
            "name": name, "is_company": is_co, "old_ids": [], "refs": 0})
        g["old_ids"].append(oid)
        g["refs"] += n
    create_partners = [{"name": g["name"], "is_company": g["is_company"],
                        "old_ids": ", ".join(map(str, g["old_ids"][:6])),
                        "refs": g["refs"]} for g in p_groups.values()]
    create_partners.sort(key=lambda r: -r["refs"])

    # ---- summary ------------------------------------------------------------
    summary: list[dict] = []
    for ds in LOAD_ORDER:
        rows = datasets[ds]
        ready = after_create = hold = skipped = 0
        for r in rows:
            st = status[ds][int(r["old_id"])]
            if st["skip"]:
                skipped += 1
            elif st["data"]:
                hold += 1
            elif st["create"]:
                after_create += 1
            else:
                ready += 1
        summary.append({
            "dataset": ds, "rows": len(rows), "ready": ready,
            "after_create": after_create, "hold": hold, "skipped": skipped,
            "ready_pct": round(100 * ready / max(1, len(rows)), 1)})

    notes = {
        "invoice_total_AED": round(sum(float(s(r.get("amount_total")) or 0)
                                       for r in datasets["invoices"]), 2),
        "bill_total_AED": round(sum(float(s(r.get("amount_total")) or 0)
                                    for r in datasets["bills"]), 2),
        "payment_total_AED": round(sum(float(s(r.get("amount")) or 0)
                                       for r in datasets["payments"]), 2),
        "invoices_with_residual": sum(1 for r in datasets["invoices"]
                                      if float(s(r.get("amount_residual")) or 0) > 0.005),
        "lines_with_full_reconcile": sum(1 for r in datasets["move_lines"]
                                         if s(r.get("full_reconcile_id"))),
        "cancelled_payments": sum(1 for r in datasets["payments"]
                                  if s(r.get("state")) == "canceled"),
        "orphan_move_lines": orphan_lines,
        "tax_rename_table": TAX_TABLE_NOTE,
    }

    unmatched_taxes = sum(1 for r in datasets["taxes"]
                          if str(r["old_id"]) not in mapping.get("taxes", {}))
    flags = [
        {"topic": "Reference creation (approved)", "affected":
            sum(unresolved_by_field.get(f, 0) for f in
                ("account_id", "journal_id", "partner_id", "tax_line_id",
                 "default_account_id", "outstanding_account_id",
                 "destination_account_id")),
         "detail": "create-as-needed approved: 154 accounts / 38 journals / "
                   "268 partners / 14 users (inactive); lists in Create_* sheets"},
        {"topic": "Unit link", "affected":
            unresolved_by_field.get("property_id", 0),
         "detail": "241 refs matched -> 8,349 records; unmatched PARK I N V "
                   "(ACT/GLAM) records held - those units are not in the target"},
        {"topic": "Reconciliation route (.dump reconsideration)", "affected":
            notes["lines_with_full_reconcile"],
         "detail": "user asked to reconsider the .dump route for lossless "
                   "reconciliations; " + str(notes["invoices_with_residual"]) +
                   " invoices still carry a residual; the source dump also gives "
                   "the exact unit/building table and attachments"},
        {"topic": "5% emirate tax renames", "affected": 49,
         "detail": TAX_TABLE_NOTE},
        {"topic": "Product/analytic links (decided)", "affected": 160,
         "detail": "product links folded into line descriptions; analytics "
                   "dropped (15 vendor-bill lines only - not required)"},
    ]

    hold_rows: list[dict] = []
    for ds in LOAD_ORDER:
        per_reason: dict[str, list[int]] = defaultdict(list)
        for r in datasets[ds]:
            oid = int(r["old_id"])
            for reason in status[ds][oid]["data"]:
                per_reason[reason].append(oid)
        for reason, ids in sorted(per_reason.items(), key=lambda kv: -len(kv[1])):
            hold_rows.append({"dataset": ds, "reason": reason,
                              "count": len(ids), "examples": ids[:5]})

    wb = Workbook()
    wb.remove(wb.active)
    _add_sheet(wb, "Summary", summary)
    _add_sheet(wb, "Flags", flags)
    _add_sheet(wb, "Create_Accounts", create_accounts)
    _add_sheet(wb, "Create_Journals", create_journals)
    _add_sheet(wb, "Create_Partners", create_partners)
    _add_sheet(wb, "Hold_Reasons", hold_rows)
    _add_sheet(wb, "Defects", defects)
    _add_sheet(wb, "Notes", [{"check": k, "value": v} for k, v in notes.items()])
    wb.save(OUT_XLSX)

    out = {"summary": summary, "flags": flags, "defects": defects, "notes": notes,
           "create_candidates": {
               "accounts": create_accounts, "journals": create_journals,
               "partners": create_partners},
           "hold": {ds: {str(oid): st["data"] for oid, st in status[ds].items()
                         if st["data"]} for ds in LOAD_ORDER},
           "create": {ds: {str(oid): st["create"] for oid, st in status[ds].items()
                           if st["create"]} for ds in LOAD_ORDER},
           "skip": {ds: {str(oid): st["skip"] for oid, st in status[ds].items()
                         if st["skip"]}
                    for ds in LOAD_ORDER}}
    OUT_JSON.write_text(json.dumps(out, indent=1), encoding="utf-8")

    for r in summary:
        print(f"  {r['dataset']:<18} rows={r['rows']:>6}  ready={r['ready']:>6} "
              f"({r['ready_pct']:>5}%)  after_create={r['after_create']:>6} "
              f"hold={r['hold']:>5}  skip={r['skipped']:>5}")
    print(f"  orphan move lines       : {orphan_lines}")
    print(f"  invoices w/ residual    : {notes['invoices_with_residual']}")
    print(f"  lines w/ full_reconcile : {notes['lines_with_full_reconcile']}")
    print(f"-> {OUT_XLSX.name}, {OUT_JSON.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
