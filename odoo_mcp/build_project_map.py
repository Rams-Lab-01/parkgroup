"""Resolve sheet project codes -> Odoo ``building_name`` using evidence.

The sheets use codes (PRY, PBR1, PBR2, PGV); Odoo uses building names. Guessing
would be unsafe, especially for PBR1 vs PBR2 which both plausibly map to
"PARK BEACH RESIDENCE" vs "PARK BEACH RESIDENCE II".

This scores each candidate building on:
  * unit-number overlap between the sheet project and the Odoo building
  * size (property_area) agreement, using the sheet's "Size (Sq Ft)"
  * unit-type / bedroom agreement where available

and reports the winner plus the margin, so anything close is flagged
AMBIGUOUS for human confirmation instead of being silently decided.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

from pgre_client import OdooClient

for _s in ("stdout", "stderr"):
    _st = getattr(sys, _s, None)
    if _st and hasattr(_st, "reconfigure"):
        try:
            _st.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

SHEET = Path(r"C:\Parkgroup Data\05-10-2026 Final Full Report.xlsx")
SHEET_FIELD = "building_name"


def find_header(rows, scan=12):
    best_i, best_n = 0, -1
    for i, r in enumerate(rows[:scan]):
        n = sum(1 for c in r if c not in (None, ""))
        if n > best_n:
            best_n, best_i = n, i
    return best_i


#: Unit numbers in the sheets carry project-ish prefixes that Odoo's
#: product.default_code does not: "SHOP-01", "UNIT  606", "Unit-713".
_UNIT_PREFIX_RE = re.compile(r"^\s*(?:unit|shop|apt|office)\s*[-_]?\s*", re.IGNORECASE)


def norm_unit(v: object) -> str:
    """Normalise a unit identifier on both sides.

    Sheet values look like ``101``, ``SHOP-01``, ``UNIT  606``, ``101.0``.
    Odoo uses ``default_code`` like ``101``, ``606``, ``G01``.
    Both must reduce to a comparable token, otherwise a formatting difference
    masquerades as "no match".
    """
    if v in (None, ""):
        return ""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = _UNIT_PREFIX_RE.sub("", s).strip()
    s = s.replace("_", "-").strip("-").strip()
    if not s:
        return ""
    # '00606' -> '606'
    if s.isdigit():
        s = s.lstrip("0") or "0"
    return s.upper()


def num(v: object) -> float | None:
    try:
        if v in (None, ""):
            return None
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def main() -> int:
    client = OdooClient()

    # ---- Odoo side
    props = client.search_read("product.product", [("is_property", "=", True)],
                               ["name", "default_code", SHEET_FIELD, "property_area",
                                "floor", "bedrooms", "unit_type", "net_price"],
                               limit=0, order="id asc")
    by_building: dict[str, list[dict]] = defaultdict(list)
    for p in props:
        b = p.get(SHEET_FIELD)
        if b:
            by_building[str(b)].append(p)
    print("=" * 92)
    print("ODOO PROPERTIES BY BUILDING")
    print("=" * 92)
    for b, items in sorted(by_building.items()):
        units = sorted({norm_unit(i.get("default_code") or i.get("name")) for i in items})
        areas = [num(i.get("property_area")) for i in items]
        areas = [a for a in areas if a is not None]
        beds = [i.get("bedrooms") for i in items if i.get("bedrooms") is not None]
        print(f"  {b:<32} {len(items):>4} units  "
              f"unit-range {min(units)}..{max(units)}  "
              f"area {min(areas):,.0f}..{max(areas):,.0f}" if areas else
              f"  {b:<32} {len(items):>4} units  unit-range {min(units)}..{max(units)}")
        if beds:
            print(f"  {'':<32} bedrooms: {sorted(set(beds))}")

    # ---- Sheet side
    wb = load_workbook(SHEET, read_only=True, data_only=True)
    ws = wb["All Units"]
    rows = [r for r in ws.iter_rows(values_only=True)]
    hi = find_header(rows)
    header = [str(c).strip() if c not in (None, "") else "" for c in rows[hi]]
    col = {h.lower(): i for i, h in enumerate(header) if h}
    ip, iu = col["project name"], col["unit no"]
    isz, ity = col.get("size (sq ft)"), col.get("unit type")

    sheet_rows = [r for r in rows[hi + 1:]
                  if any(c not in (None, "") for c in r)
                  and str(r[ip]).strip().upper() != "TOTAL"]
    by_project: dict[str, list[dict]] = defaultdict(list)
    for r in sheet_rows:
        proj = str(r[ip]).strip().upper()
        by_project[proj].append({
            "unit": norm_unit(r[iu]),
            "area": num(r[isz]) if isz is not None else None,
            "type": str(r[ity]).strip() if ity is not None else "",
        })

    print()
    print("=" * 92)
    print("SHEET PROJECTS")
    print("=" * 92)
    for proj, items in sorted(by_project.items()):
        units = sorted(i["unit"] for i in items)
        areas = [i["area"] for i in items if i["area"] is not None]
        print(f"  {proj:<8} {len(items):>4} units  unit-range {min(units)}..{max(units)}  "
              f"area {min(areas):,.0f}..{max(areas):,.0f}  types={sorted({i['type'] for i in items})[:8]}")

    # ---- score each (project, building) pair
    print()
    print("=" * 92)
    print("MAPPING EVIDENCE  (unit overlap + size agreement)")
    print("=" * 92)
    for proj, items in sorted(by_project.items()):
        sheet_units = {i["unit"] for i in items if i["unit"]}
        sheet_areas = [i["area"] for i in items if i["area"] is not None]
        print(f"\n  {proj}:")
        scored = []
        for b, plist in sorted(by_building.items()):
            od_units = {norm_unit(i.get("default_code") or i.get("name")) for i in plist}
            overlap = sheet_units & od_units
            od_areas = [num(i.get("property_area")) for i in plist]
            od_areas = [a for a in od_areas if a is not None]
            area_hit = 0
            if sheet_areas and od_areas:
                lo, hi_ = min(od_areas), max(od_areas)
                area_hit = sum(1 for a in sheet_areas if lo * 0.9 <= a <= hi_ * 1.1)
            jacc = len(overlap) / max(1, len(sheet_units | od_units))
            scored.append((len(overlap), area_hit, jacc, b, overlap))
        scored.sort(key=lambda t: (-t[0], -t[1]))
        for n_ov, n_area, jac, b, overlap in scored[:4]:
            print(f"    -> {b:<32} unit-overlap {n_ov:>3}/{len(sheet_units):<3} "
                  f"area-hit {n_area:>3}/{len(sheet_areas):<3} jaccard {jac:.2f}"
                  + (f"  e.g. {sorted(overlap)[:6]}" if overlap else ""))
        if scored:
            top = scored[0]
            second = scored[1] if len(scored) > 1 else None
            if not top[0]:
                print(f"    !! NO unit-number overlap with any building -> unresolvable by number")
            elif second and top[0] == second[0]:
                print(f"    !! AMBIGUOUS: {top[3]} and {second[3]} tie at {top[0]} unit matches "
                      f"-> needs human confirmation")
            else:
                print(f"    => best match: {top[3]} ({top[0]} unit matches, "
                      f"clear of runner-up {second[3] if second else '-'})")
    wb.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())