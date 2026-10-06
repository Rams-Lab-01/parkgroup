"""Map every old unit reference (product.template) used by the migration
datasets to the target's property.details units.

Method (no guessing):
  - the old ref carries the unit number ("[101] 101 (2095)") and its trailing
    old template id
  - the owning company identifies the project (business rule: one legal entity
    per project): PARK REAL ESTATE -> PBR1, PBR -> PBR2, PARK RESIDENCY -> PRY,
    AIWA -> PGV
  - companies without a target project (PARK I N V -> ACT/GLAM) and refs that
    do not parse stay UNMATCHED and are held

Outputs: unit_mapping_2026-10-06.xlsx and merges mapping["units"] into
target_mapping_2026-10-06.json.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(r"C:\Parkgroup Data\odoo_mcp")
sys.path.insert(0, str(ROOT))
from reconcile import _add_sheet  # noqa: E402

OLD = ROOT / "migration_out"
NEW = ROOT / "target_out"
MAP_JSON = ROOT / "target_mapping_2026-10-06.json"
OUT_XLSX = ROOT / "unit_mapping_2026-10-06.xlsx"

MOVE_DATASETS = ("invoices", "bills", "journal_entries", "customer_refunds",
                 "vendor_refunds", "receipts")
COMPANY_PROJECT = {
    "PARK REAL ESTATE DEVELOPMENT LLC OPC": "PBR1",
    "PBR REAL ESTATE DEVELOPMENT LLC OPC": "PBR2",
    "PARK RESIDENCY REAL ESTATE DEVELOPMENT LLC": "PRY",
    "AIWA REAL ESTATE DEVELOPMENT LLC": "PGV",
}
REF_NUM = re.compile(r"^\[(?P<u>[^\]]+)\]")
REF_PLAIN = re.compile(r"^(?P<u>\d+)\s*\(")


def s(value: object) -> str:
    if value in (None, "", "False", "None"):
        return ""
    return str(value).strip()


def ref_parts(value: str) -> tuple[str, int] | None:
    v = s(value)
    if not v:
        return None
    m = re.match(r"^(.*?)\s*\((\d+)\)$", v)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def project_code_from_name(name: str) -> str:
    n = name.lower()
    if "beach residence ii" in n:
        return "PBR2"
    if "beach residence i" in n:
        return "PBR1"
    if "residency" in n:
        return "PRY"
    if "golf" in n:
        return "PGV"
    return ""


def norm_unit(v: str) -> str:
    v = s(v)
    return str(int(v)) if v.isdigit() else v.upper()


def main() -> int:
    units = list(csv.DictReader((NEW / "units.csv").open(encoding="utf-8-sig")))
    projects = {r["id"]: s(r.get("name"))
                for r in csv.DictReader((NEW / "projects.csv").open(encoding="utf-8-sig"))}
    by_key: dict[tuple[str, str], dict] = {}
    for u in units:
        proj_name = projects.get((u.get("project_id") or "").split("|")[0], "")
        code = project_code_from_name(proj_name)
        by_key[(code, norm_unit(u.get("unit_number", "")))] = u

    seen: dict[int, dict] = {}
    counts: Counter = Counter()
    unmatched: Counter = Counter()
    unmatched_examples: defaultdict = defaultdict(list)
    for ds in MOVE_DATASETS + ("payments",):
        rows = list(csv.DictReader((OLD / f"{ds}.csv").open(encoding="utf-8-sig")))
        for r in rows:
            pv = s(r.get("property_id"))
            if not pv:
                continue
            parts = ref_parts(pv)
            if not parts:
                unmatched["unparseable ref"] += 1
                unmatched_examples["unparseable ref"].append(pv)
                continue
            disp, old_id = parts
            company = (ref_parts(s(r.get("company_id"))) or ("", 0))[0]
            code = COMPANY_PROJECT.get(company, "")
            m = REF_NUM.match(disp) or REF_PLAIN.match(disp)
            unit_no = m.group("u") if m else ""
            tgt = by_key.get((code, norm_unit(unit_no))) if code and unit_no else None
            if tgt:
                seen.setdefault(old_id, {"old_ref": pv, "old_name": disp,
                                         "project": code, "unit_no": unit_no,
                                         "new_id": tgt["id"], "new_name": s(tgt.get("name")),
                                         "method": "company+unit"})
                counts[old_id] += 1
            else:
                reason = ("company has no target project" if not code
                          else "unit not found in target project")
                unmatched[reason] += 1
                unmatched_examples[reason].append(f"{pv} / {company}")
    matched_refs = [
        {**v, "datasets_refs": counts[k]} for k, v in sorted(seen.items())]
    unmatched_rows = []
    for reason, cnt in unmatched.items():
        for ex in unmatched_examples[reason][:12]:
            unmatched_rows.append({"reason": reason, "count": cnt, "example": ex})

    mapping = json.loads(MAP_JSON.read_text(encoding="utf-8"))
    mapping["units"] = {str(k): {"new_id": int(v["new_id"]), "method": v["method"],
                                 "project": v["project"], "unit": v["unit_no"]}
                        for k, v in seen.items()}
    MAP_JSON.write_text(json.dumps(mapping, indent=1), encoding="utf-8")

    summary = [{"metric": "old unit refs matched", "value": len(seen)},
               {"metric": "refs unmatched (all datasets)", "value": sum(unmatched.values())},
               {"metric": "target units", "value": len(units)}]
    wb = Workbook()
    wb.remove(wb.active)
    _add_sheet(wb, "Summary", summary)
    _add_sheet(wb, "Matched", matched_refs)
    _add_sheet(wb, "Unmatched", unmatched_rows or [{"reason": "(none)"}])
    wb.save(OUT_XLSX)

    print(f"  matched old unit refs : {len(seen)}  (target units {len(units)})")
    print(f"  unmatched refs        : {sum(unmatched.values())}  {dict(unmatched)}")
    print(f"  refs usage (top 5)    : {counts.most_common(5)}")
    print(f"-> {OUT_XLSX.name} + mapping['units'] merged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
