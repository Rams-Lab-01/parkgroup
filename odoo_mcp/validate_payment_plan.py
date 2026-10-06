"""Validate unit installments against project-declared payment plan.

Inputs:
- Unit Payment Collection sheet (from Consolidated_Sales_Workbook (4).xlsx or 05-10-2026 Full Report)
- Payment Plan Structure sheet (same workbook)

Logic:
1. Load project -> plan description from Payment Plan Structure (only the 4 main projects)
2. For each unit with Sold Price and 10%/20% data:
   - Determine expected plan type from project's declared plan
   - Validate installments match that plan type
   - Flag mismatches as AMBIGUOUS (do not copy)
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

ROOT = Path(r"C:\Parkgroup Data")
PLAN_WB = ROOT / "Consolidated_Sales_Workbook (4).xlsx"
FULL_REPORT = ROOT / "05-10-2026 Final Full Report.xlsx"

UNIT_SHEET = PLAN_WB if PLAN_WB.exists() else FULL_REPORT
PLAN_SHEET_NAME = "Payment Plan Structure"
UNIT_SHEET_NAME = "Unit Payment Collection"


def find_header(rows, scan: int = 12) -> int:
    best_i, best_n = 0, -1
    for i, r in enumerate(rows[:scan]):
        n = sum(1 for c in r if c not in (None, ""))
        if n > best_n:
            best_n, best_i = n, i
    return best_i


def load_plan_map(wb_path: Path) -> dict[str, str]:
    """Return {project_code: plan_description} from Payment Plan Structure sheet.
    Only the first 4 data rows are the main projects (PGV, PBR2, PBR1, PRY)."""
    wb = load_workbook(wb_path, read_only=True, data_only=True)
    ws = wb[PLAN_SHEET_NAME]
    rows = [r for r in ws.iter_rows(values_only=True)]
    wb.close()
    hi = find_header(rows)
    hdr = [str(c).strip() if c not in (None, "") else "" for c in rows[hi]]
    # Find Project and Plan Summary columns
    try:
        proj_col = hdr.index("Project")
        plan_col = hdr.index("Plan Summary")
    except ValueError as e:
        print(f"  ERROR: expected columns not found: {hdr}")
        raise
    out: dict[str, str] = {}
    # Only the FIRST 4 data rows are the main projects
    for i, r in enumerate(rows[hi + 1:hi + 5]):
        if len(r) <= max(proj_col, plan_col):
            continue
        proj = r[proj_col]
        plan = r[plan_col]
        if isinstance(proj, str) and proj.strip():
            # Extract code like "PGV (Park Group Villas)" -> "PGV"
            m = re.match(r"\s*([A-Z0-9]{2,4})\s*\(", proj.strip())
            code = m.group(1) if m else proj.strip().split()[0]
            out[code.upper()] = str(plan).strip()
    return out


def load_units(wb_path: Path) -> list[dict]:
    wb = load_workbook(wb_path, read_only=True, data_only=True)
    ws = wb[UNIT_SHEET_NAME]
    rows = [r for r in ws.iter_rows(values_only=True)]
    wb.close()
    hi = find_header(rows)
    hdr = [str(c).strip() if c not in (None, "") else "" for c in rows[hi]]
    col = {name: i for i, name in enumerate(hdr) if name}
    required = ["Project Name", "Unit No", "Client Name", "Status", "Sold Price (AED)",
                "10% Payment Date", "10% Amount (AED)", "10% Status",
                "20% Payment Date", "20% Amount (AED)", "20% Status"]
    missing = [f for f in required if f not in col]
    if missing:
        print(f"  WARNING: missing columns: {missing}")
    units = []
    for r in rows[hi + 1:]:
        if not r or len(r) < hi:
            continue
        proj_name = r[col.get("Project Name", -1)] if "Project Name" in col else None
        if not proj_name or not str(proj_name).strip():
            continue
        unit = {
            "project": str(proj_name).strip(),
            "unit_no": r[col.get("Unit No", -1)] if "Unit No" in col else None,
            "client": r[col.get("Client Name", -1)] if "Client Name" in col else None,
            "status": str(r[col.get("Status", -1)]).strip() if "Status" in col else "",
            "sold_price": r[col.get("Sold Price (AED)", -1)] if "Sold Price (AED)" in col else None,
            "p10_date": r[col.get("10% Payment Date", -1)] if "10% Payment Date" in col else None,
            "p10_amt": r[col.get("10% Amount (AED)", -1)] if "10% Amount (AED)" in col else None,
            "p10_status": r[col.get("10% Status", -1)] if "10% Status" in col else None,
            "p20_date": r[col.get("20% Payment Date", -1)] if "20% Payment Date" in col else None,
            "p20_amt": r[col.get("20% Amount (AED)", -1)] if "20% Amount (AED)" in col else None,
            "p20_status": r[col.get("20% Status", -1)] if "20% Status" in col else None,
        }
        units.append(unit)
    return units


def classify_plan(description: str) -> str:
    """Return normalized plan type: CLP, BOOKING_SPA, REGULATORY, OTHER, or UNKNOWN."""
    d = description.lower()
    if "regulatory milestone" in d:
        return "REGULATORY"
    if "construction-linked" in d and ("10%" in d or "20%" in d):
        return "CLP"
    if "booking" in d and ("spa" in d or "early stage" in d):
        return "BOOKING_SPA"
    if "milestone" in d:
        return "MILESTONE"
    return "OTHER"


def validate_unit(unit: dict, plan_type: str) -> list[str]:
    """Return list of validation messages; empty means OK."""
    msgs: list[str] = []
    sold = unit["sold_price"]
    if sold is None or (isinstance(sold, str) and not str(sold).strip()):
        msgs.append("missing sold price")
        return msgs
    try:
        sold_f = float(sold)
    except (TypeError, ValueError):
        msgs.append("sold price not numeric")
        return msgs

    p10_date, p10_amt, p10_status = unit["p10_date"], unit["p10_amt"], unit["p10_status"]
    p20_date, p20_amt, p20_status = unit["p20_date"], unit["p20_amt"], unit["p20_status"]

    def parse_date(d):
        if isinstance(d, datetime):
            return d.date()
        if isinstance(d, str):
            try:
                return datetime.strptime(d[:10], "%Y-%m-%d").date()
            except ValueError:
                return None
        return None

    d10 = parse_date(p10_date) if p10_date else None
    d20 = parse_date(p20_date) if p20_date else None

    s10 = str(p10_status).strip().upper() if p10_status else ""
    s20 = str(p20_status).strip().upper() if p20_status else ""

    # 1. Validate CLP plan (10%/20% milestones)
    if plan_type == "CLP":
        if p10_date is None:
            msgs.append("10% payment date missing")
        elif p10_amt is None:
            msgs.append("10% amount missing")
        else:
            try:
                amt10 = float(p10_amt)
                expected = round(sold_f * 0.10, 2)
                if abs(amt10 - expected) > 1.0:
                    msgs.append(f"10% amount mismatch: got {amt10}, expected {expected} (10% of {sold_f})")
            except (TypeError, ValueError):
                msgs.append("10% amount not numeric")

        if p20_date is None:
            msgs.append("20% payment date missing")
        elif p20_amt is None:
            msgs.append("20% amount missing")
        else:
            try:
                amt20 = float(p20_amt)
                expected = round(sold_f * 0.20, 2)
                if abs(amt20 - expected) > 1.0:
                    msgs.append(f"20% amount mismatch: got {amt20}, expected {expected} (20% of {sold_f})")
            except (TypeError, ValueError):
                msgs.append("20% amount not numeric")

        if d10 and d20 and d20 < d10:
            msgs.append("20% date before 10% date")

        if s10 == "PAID" and not d10:
            msgs.append("10% status PAID but no date")
        if s20 == "PAID" and not d20:
            msgs.append("20% status PAID but no date")

    # 2. Validate BOOKING_SPA plan (PGV: reservation + SPA, no 10%/20%)
    elif plan_type == "BOOKING_SPA":
        if p10_amt is not None:
            try:
                amt10 = float(p10_amt)
                if amt10 > 1000:
                    msgs.append(f"10% amount present ({amt10}) contradicts BOOKING_SPA plan (PGV has no 10%/20% milestones)")
            except (TypeError, ValueError):
                pass
        if p20_amt is not None:
            try:
                amt20 = float(p20_amt)
                if amt20 > 1000:
                    msgs.append(f"20% amount present ({amt20}) contradicts BOOKING_SPA plan (PGV has no 10%/20% milestones)")
            except (TypeError, ValueError):
                pass

    # 3. Validate REGULATORY plan (PRY: BF->SPA->Oqood)
    elif plan_type == "REGULATORY":
        if p10_amt is not None:
            try:
                amt10 = float(p10_amt)
                if amt10 > 1000:
                    msgs.append(f"10% amount present ({amt10}) may contradict REGULATORY plan (PRY uses BF->SPA->Oqood milestones)")
            except (TypeError, ValueError):
                pass
        if p20_amt is not None:
            try:
                amt20 = float(p20_amt)
                if amt20 > 1000:
                    msgs.append(f"20% amount present ({amt20}) may contradict REGULATORY plan (PRY uses BF->SPA->Oqood milestones)")
            except (TypeError, ValueError):
                pass

    # 4. OTHER / UNKNOWN: do basic sanity checks
    else:
        if p10_amt is not None:
            try:
                amt10 = float(p10_amt)
                if abs(amt10 - round(sold_f * 0.10, 2)) > 1.0:
                    msgs.append(f"10% amount not 10% of sold price: {amt10} vs {round(sold_f*0.10,2)}")
            except (TypeError, ValueError):
                pass
        if p20_amt is not None:
            try:
                amt20 = float(p20_amt)
                if abs(amt20 - round(sold_f * 0.20, 2)) > 1.0:
                    msgs.append(f"20% amount not 20% of sold price: {amt20} vs {round(sold_f*0.20,2)}")
            except (TypeError, ValueError):
                pass

    return msgs


def map_project_to_code(project_name: str) -> str | None:
    """Map sheet project name/code to plan code (PGV, PBR1, PBR2, PRY)."""
    p = project_name.upper().strip()
    alias = {
        "PARK BEACH RESIDENCE": "PBR1",
        "PARK BEACH RESIDENCE II": "PBR2",
        "PARK GOLF VIEW RESIDENCE": "PGV",
        "PARK RESIDENCY": "PRY",
        "GLAM RESIDENCE": "GLAM",
        "AJMAN CREEK TOWER 1": "ACT1",
        "AJMAN CREEK TOWER 2": "ACT2",
        # Direct codes used in the Unit Payment Collection sheet
        "PBR1": "PBR1",
        "PBR2": "PBR2",
        "PGV": "PGV",
        "PRY": "PRY",
        "GLAM": "GLAM",
        "ACT1": "ACT1",
        "ACT2": "ACT2",
    }
    if p in alias:
        return alias[p]
    for name, code in alias.items():
        if name.upper() in p:
            return code
    return None
    return None


def main() -> int:
    print("=" * 80)
    print("LOADING PLAN MAP")
    print("=" * 80)
    plan_map = load_plan_map(PLAN_WB)
    print(f"Loaded {len(plan_map)} project -> plan mappings:")
    for code, desc in sorted(plan_map.items()):
        safe = desc.encode("utf-8", errors="replace").decode("utf-8")
        print(f"  {code}: {safe[:100]}")

    print()
    print("=" * 80)
    print("LOADING UNITS")
    print("=" * 80)
    units = load_units(UNIT_SHEET)
    print(f"Loaded {len(units)} units with project info")

    print()
    print("=" * 80)
    print("VALIDATING EACH UNIT")
    print("=" * 80)
    ambiguous = []
    ok = 0
    for u in units:
        code = map_project_to_code(u["project"])
        if code is None:
            # fallback: take first letters of each word up to 4
            parts = re.findall(r"[A-Z]", u["project"])
            code = "".join(parts[:4]) if len(parts) >= 2 else u["project"][:4].upper()
        plan_desc = plan_map.get(code, "")
        plan_type = classify_plan(plan_desc) if plan_desc else "UNKNOWN"
        issues = validate_unit(u, plan_type)
        # Only validate SOLD units; Available units are not expected to pay yet
        if u["status"].upper() != "SOLD":
            ok += 1  # not sold -> no payment expectation
        elif issues:
            ambiguous.append((u, code, plan_type, plan_desc, issues))
        else:
            ok += 1

    print(f"Units OK: {ok}")
    print(f"Units AMBIGUOUS (mismatch): {len(ambiguous)}")
    if ambiguous:
        print()
        print("=" * 80)
        print("AMBIGUOUS UNITS (first 25)")
        print("=" * 80)
        for u, code, plan_type, plan_desc, issues in ambiguous[:25]:
            print(f"\n{u['project']} Unit {u['unit_no']} (client: {u['client']})")
            print(f"  Declared plan ({code}): {plan_desc[:100]}")
            print(f"  Normalized type: {plan_type}")
            print(f"  Sold: {u['sold_price']} AED")
            print(f"  10%: date={u['p10_date']} amt={u['p10_amt']} status={u['p10_status']}")
            print(f"  20%: date={u['p20_date']} amt={u['p20_amt']} status={u['p20_status']}")
            print(f"  Issues: {'; '.join(issues)}")

    # Summary by project
    print()
    print("=" * 80)
    print("AMBIGUOUS SUMMARY BY PROJECT")
    print("=" * 80)
    from collections import Counter
    amb_by_proj = Counter()
    for u, code, plan_type, _, _ in ambiguous:
        amb_by_proj[(u["project"], code, plan_type)] += 1
    for (proj, code, ptype), cnt in sorted(amb_by_proj.items()):
        print(f"  {proj} ({code}, plan={ptype}): {cnt} ambiguous")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())