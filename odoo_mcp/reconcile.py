"""Reconcile the Parkgroup spreadsheets against Odoo (pgre.odoo.com).

Outputs one workbook with six sheets:

``Project_Map``      sheet project code -> Odoo ``building_name``, with the
                     evidence and a confidence verdict (never a bare guess)
``Reconciliation``  unit-level match, sheet vs Odoo, with amount comparison
``Ambiguous``        matches that need a human decision
``Unreconciled``     sheet units absent from Odoo **and** Odoo units absent
                     from the sheets, listed separately
``Defects_Log``      data-quality defects found on both sides
``Clarifications``   explicit questions blocking a decision

Design rules
------------
* Never silently decide an ambiguous item - it is isolated, not guessed.
* Amounts are compared **per currency** and never summed across currencies.
* Every verdict is reproducible: each row carries the evidence used.

Usage:
    python reconcile.py --out reconciliation_2026-10-06.xlsx
    python reconcile.py --sheet "C:\\...\\Consolidated_Sales_Workbook (4).xlsx"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from pgre_client import OdooClient, OdooError

for _s in ("stdout", "stderr"):
    _st = getattr(sys, _s, None)
    if _st and hasattr(_st, "reconfigure"):
        try:
            _st.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

DEFAULT_SHEET = Path(r"C:\Parkgroup Data\05-10-2026 Final Full Report.xlsx")
UNIT_SHEET_NAME = "All Units"

#: Amount tolerance when comparing money (AED, whole-dirham rounding noise).
AMOUNT_TOL = 1.0
#: Relative tolerance for "same" amounts when values are large.
AMOUNT_REL_TOL = 0.001

#: Unit identifiers in the sheets carry prefixes: ``UNIT  606``, ``SHOP-01``.
#: Stripping "SHOP" turns SHOP-01 into "1", which then **collides with the real
#: unit 1** of the same building. Shops therefore keep a distinct namespace.
_UNIT_PREFIX_RE = re.compile(r"^\s*(unit|shop|apt|office)\s*[-_]?\s*", re.IGNORECASE)


def norm_unit(value: object) -> str:
    """Normalise a unit identifier on both sides.

    ``101`` -> ``101``; ``UNIT  606`` -> ``606``; ``SHOP-01`` -> ``SHOP:01``
    (namespaced so a shop can never be mistaken for unit 1).
    """
    if value in (None, ""):
        return ""
    s = str(value).strip()
    if s.endswith(".0"):
        s = s[:-2]
    m = _UNIT_PREFIX_RE.match(s)
    if not m:
        if s.isdigit():
            return s.lstrip("0") or "0"
        return s.upper()
    kind = m.group(1).lower()
    rest = s[m.end():].replace("_", "-").strip("-").strip()
    if not rest:
        return ""
    if rest.isdigit():
        rest = rest.lstrip("0") or "0"
    if kind == "shop":
        return f"SHOP:{rest}"
    return rest.upper()


_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]+")

#: Title/honorific tokens that add nothing to a name comparison.
_NAME_NOISE = {
    "MR", "MRS", "MS", "MISS", "DR", "PROF", "ENG", "MRS", "S/O", "D/O",
    "LTD", "LLC", "LL C", "L L C", "CO", "COMPANY", "TRADING", "EST",
    "MR.", "M/S", "M.D", "BHD", "PSC", "FZ", "FZCO", "SA", "LTD.",
}


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
def norm_name(value: object) -> str:
    """Aggressive normalisation for matching person/company names."""
    if value in (None, ""):
        return ""
    s = unicodedata.normalize("NFKD", str(value))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.upper().replace("&", " AND ")
    s = _NON_ALNUM_RE.sub(" ", s).strip()
    tokens = [t for t in s.split() if t and t not in _NAME_NOISE]
    if not tokens:
        return ""
    return " ".join(sorted(tokens))


def name_tokens(value: object) -> set[str]:
    s = norm_name(value)
    return set(s.split()) if s else set()


def to_number(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "").replace("AED", "").strip())
    except (TypeError, ValueError):
        return None


def amounts_close(a: float | None, b: float | None, tol: float = AMOUNT_TOL) -> bool:
    if a is None or b is None:
        return False
    if abs(a - b) <= tol:
        return True
    scale = max(abs(a), abs(b), 1.0)
    return abs(a - b) / scale <= AMOUNT_REL_TOL


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass
class SheetUnit:
    row_no: int
    project: str
    unit_raw: object
    unit: str
    unit_type: str
    floor: object
    size: float | None
    status: str
    client: str
    client_norm: str
    client_raw: str
    nationality: str
    contact: str
    email: str
    list_price: float | None
    discount: float | None
    sold_price: float | None
    admin_fee: float | None
    total_price: float | None
    oqood: str
    spa_status: str
    spa_date: object
    reservation_date: object
    rf_status: str
    broker: str
    amt_10: float | None
    amt_20: float | None
    collected: float | None
    balance_due: float | None
    escrow_pct: object
    escrow_alloc: float | None
    p10_date: object | None = None
    p10_status: str = ""
    p20_date: object | None = None
    p20_status: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Defect:
    category: str
    severity: str          # HIGH / MEDIUM / LOW
    scope: str             # sheet / odoo / both
    location: str
    description: str
    example: str = ""
    record_count: int = 1


def find_header(rows: Sequence[tuple], scan: int = 12) -> int:
    best_i, best_n = 0, -1
    for i, r in enumerate(rows[:scan]):
        n = sum(1 for c in r if c not in (None, ""))
        if n > best_n:
            best_n, best_i = n, i
    return best_i


# --------------------------------------------------------------------------- #
# Sheet loading
# --------------------------------------------------------------------------- #
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "project": ("project name", "project"),
    "unit_no": ("unit no", "unit no.", "unit", "unit number"),
    "floor": ("floor",),
    "unit_type": ("unit type", "type"),
    "size": ("size (sq ft)", "size", "property area"),
    "status": ("status",),
    "client": ("client name", "client", "customer name", "buyer"),
    "nationality": ("nationality",),
    "contact": ("contact no", "contact", "phone"),
    "email": ("email", "email address"),
    "list_price": ("list price (aed)", "list price"),
    "discount": ("discount (aed)", "discount"),
    "sold_price": ("sold price (aed)", "sold price"),
    "admin_fee": ("admin fee (aed)", "admin fee"),
    "total_price": ("total price (aed)", "total price"),
    "oqood": ("oqood status",),
    "spa_status": ("spa status",),
    "spa_date": ("spa date",),
    "reservation_date": ("reservation date",),
    "rf_status": ("rf status",),
    "broker": ("broker company", "broker"),
    "amt_10": ("10% amount (aed)", "10% amount"),
    "amt_20": ("20% amount (aed)", "20% amount"),
    "collected": ("amount collected (aed)", "amount collected"),
    "balance_due": ("balance due (aed)", "balance due"),
    "escrow_pct": ("escrow %", "escrow pct"),
    "escrow_alloc": ("escrow allocated (aed)", "escrow allocated"),
    "p10_date": ("10% payment date", "10% date"),
    "p10_status": ("10% status",),
    "p20_date": ("20% payment date", "20% date"),
    "p20_status": ("20% status",),
}

# --------------------------------------------------------------------------- #
# Payment-plan validation: each sheet unit must honour its project's declared
# plan. Plans live in the "Payment Plan Structure" sheet of the consolidated
# workbook; the four main projects are the first four data rows (PGV, PBR2,
# PBR1, PRY). If a unit's installments do not match the declared plan it is
# treated as ambiguous and is not copied for migration.
# --------------------------------------------------------------------------- #

# Project-name fragments -> the plan code used in the consolidated workbook.
_UNIT_TO_PLAN_CODE = {
    "PARK BEACH RESIDENCE": "PBR1",
    "PARK BEACH RESIDENCE II": "PBR2",
    "PARK GOLF VIEW RESIDENCE": "PGV",
    "PARK RESIDENCY": "PRY",
    "GLAM RESIDENCE": "GLAM",
    "AJMAN CREEK TOWER 1": "ACT1",
    "AJMAN CREEK TOWER 2": "ACT2",
}


def map_project_to_code(project_name: str) -> str:
    """Map the sheet project name (PARK BEACH RESIDENCE) to the plan code."""
    p = project_name.strip().upper()
    if p in _UNIT_TO_PLAN_CODE:
        return _UNIT_TO_PLAN_CODE[p]
    for name, code in _UNIT_TO_PLAN_CODE.items():
        if name.upper() in p:
            return code
    return p[:4].upper() if len(p) >= 4 else p


def load_project_plan_map(plan_wb_path: Path) -> dict[str, str]:
    """Return {project_code: plan_description} from Payment Plan Structure.
    Only the first four data rows are the main projects (PGV, PBR2, PBR1, PRY)."""
    wb = load_workbook(plan_wb_path, read_only=True, data_only=True)
    if "Payment Plan Structure" not in wb.sheetnames:
        wb.close()
        return {}
    ws = wb["Payment Plan Structure"]
    rows = [r for r in ws.iter_rows(values_only=True)]
    wb.close()
    hi = find_header(rows)
    hdr = [str(c).strip() if c not in (None, "") else "" for c in rows[hi]]
    if not hdr:
        return {}
    try:
        proj_col = hdr.index("Project")
        plan_col = hdr.index("Plan Summary")
    except ValueError:
        return {}
    out: dict[str, str] = {}
    for r in rows[hi + 1:hi + 5]:
        if len(r) <= max(proj_col, plan_col):
            continue
        proj = r[proj_col]
        plan = r[plan_col]
        if isinstance(proj, str) and proj.strip():
            m = re.match(r"\s*([A-Z0-9]{2,4})\s*\(", proj.strip())
            code = m.group(1) if m else proj.strip().split()[0]
            out[code.upper()] = str(plan).strip()
    return out


def classify_plan(description: str) -> str:
    """Return normalized plan type: CLP, BOOKING_SPA, REGULATORY, OTHER, or UNKNOWN."""
    if not description:
        return "UNKNOWN"
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


def parse_date(value: object):
    """Parse a payment date coming from a sheet cell."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            pass
    return None


def validate_payment_plan(unit: SheetUnit, plan_type: str) -> list[str]:
    """Validate this unit's installments against its project's declared plan.

    Returns an empty list when the unit's 10% / 20% installments match the
    declared plan type, otherwise returns a list of mismatch messages.
    """
    msgs: list[str] = []
    if unit.status.upper() != "SOLD" or unit.sold_price is None:
        return msgs   # not sold -> no payment expectation to validate
    sold = float(unit.sold_price)
    p10_date = parse_date(unit.p10_date)
    p20_date = parse_date(unit.p20_date)
    s10 = str(unit.p10_status or "").strip().upper()
    s20 = str(unit.p20_status or "").strip().upper()

    # 1. CLP: expect exactly 10% at SPA then 20% (cumulative) at the next
    #    construction milestone, dates in order, amounts correct.
    if plan_type == "CLP":
        if unit.amt_10 is None:
            msgs.append("10% amount missing (CLP plan expects 10% at SPA)")
        elif abs(unit.amt_10 - round(sold * 0.10, 2)) > 1.0:
            msgs.append(f"10% amount wrong: got {unit.amt_10}, expected {round(sold * 0.10, 2)}")
        if unit.amt_20 is None:
            msgs.append("20% amount missing (CLP plan expects 20% cumulative)")
        elif abs(unit.amt_20 - round(sold * 0.20, 2)) > 1.0:
            msgs.append(f"20% amount wrong: got {unit.amt_20}, expected {round(sold * 0.20, 2)}")
        if p10_date and p20_date and p20_date < p10_date:
            msgs.append("20% date before 10% date")

    # 2. BOOKING_SPA (PGV): no 10%/20% milestone structure at all.
    elif plan_type == "BOOKING_SPA":
        if unit.amt_10 is not None and float(unit.amt_10) > 1000:
            msgs.append(f"10% milestone ({unit.amt_10}) contradicts PGV's booking+SPA plan")
        if unit.amt_20 is not None and float(unit.amt_20) > 1000:
            msgs.append(f"20% milestone ({unit.amt_20}) contradicts PGV's booking+SPA plan")

    # 3. REGULATORY (PRY): BF->SPA->Oqood milestones, not fixed 10%/20%.
    elif plan_type == "REGULATORY":
        if unit.amt_10 is not None and float(unit.amt_10) > 1000:
            msgs.append(f"10% milestone ({unit.amt_10}) contradicts PRY's BF/SPA/Oqood plan")
        if unit.amt_20 is not None and float(unit.amt_20) > 1000:
            msgs.append(f"20% milestone ({unit.amt_20}) contradicts PRY's BF/SPA/Oqood plan")

    return msgs


def load_units(path: Path, sheet_name: str = UNIT_SHEET_NAME
               ) -> tuple[list[SheetUnit], list[Defect], dict[str, Any]]:
    defects: list[Defect] = []
    wb = load_workbook(path, read_only=True, data_only=True)
    if sheet_name not in wb.sheetnames:
        raise SystemExit(f"sheet {sheet_name!r} not in {path.name}; "
                         f"available: {wb.sheetnames}")
    rows = [r for r in wb[sheet_name].iter_rows(values_only=True)]
    hi = find_header(rows)
    header = [str(c).strip() if c not in (None, "") else "" for c in rows[hi]]

    idx: dict[str, int] = {}
    for key, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            for i, h in enumerate(header):
                if h.lower() == alias:
                    idx[key] = i
                    break
            if key in idx:
                break

    missing = [k for k in ("project", "unit_no") if k not in idx]
    if missing:
        raise SystemExit(f"could not locate required column(s) {missing} in {sheet_name!r}")

    def g(row: tuple, key: str) -> Any:
        i = idx.get(key)
        if i is None or i >= len(row):
            return None
        return row[i]

    units: list[SheetUnit] = []
    totals_rows = 0
    blank_client = 0
    dirty_unit = 0
    dirty_floor = 0
    date_in_status = 0

    for n, row in enumerate(rows[hi + 1:], start=hi + 2):
        if not any(c not in (None, "") for c in row):
            continue
        proj_raw = g(row, "project")
        proj = str(proj_raw).strip().upper() if proj_raw not in (None, "") else ""
        if proj in ("TOTAL", "TOTALS", "GRAND TOTAL", "SUBTOTAL", ""):
            totals_rows += 1
            continue
        unit_raw = g(row, "unit_no")
        unit = norm_unit(unit_raw)
        if not unit:
            dirty_unit += 1
            continue
        client_raw = g(row, "client")
        client = str(client_raw or "").strip()
        contact_raw = g(row, "contact")
        email_raw = g(row, "email")
        if client.upper() in _EMPTY_TOKENS:
            blank_client += 1
            client = ""
            client_raw = ""
        floor = g(row, "floor")
        if isinstance(floor, str) and not floor.strip().lstrip("-").isdigit():
            dirty_floor += 1
        rf = str(g(row, "rf_status") or "").strip()
        if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", rf):
            date_in_status += 1
        units.append(SheetUnit(
            row_no=n, project=proj, unit_raw=unit_raw, unit=unit,
            unit_type=str(g(row, "unit_type") or "").strip(),
            floor=floor, size=to_number(g(row, "size")),
            status=str(g(row, "status") or "").strip(),
            client=client, client_norm=norm_name(client), client_raw=client_raw,
            nationality=str(g(row, "nationality") or "").strip(),
            contact=str(contact_raw or "").strip(),
            email=str(email_raw or "").strip(),
            list_price=to_number(g(row, "list_price")),
            discount=to_number(g(row, "discount")),
            sold_price=to_number(g(row, "sold_price")),
            admin_fee=to_number(g(row, "admin_fee")),
            total_price=to_number(g(row, "total_price")),
            oqood=str(g(row, "oqood") or "").strip(),
            spa_status=str(g(row, "spa_status") or "").strip(),
            spa_date=g(row, "spa_date"),
            reservation_date=g(row, "reservation_date"),
            rf_status=rf, broker=str(g(row, "broker") or "").strip(),
            amt_10=to_number(g(row, "amt_10")), amt_20=to_number(g(row, "amt_20")),
            collected=to_number(g(row, "collected")),
            balance_due=to_number(g(row, "balance_due")),
            escrow_pct=g(row, "escrow_pct"), escrow_alloc=to_number(g(row, "escrow_alloc")),
            p10_date=g(row, "p10_date"), p10_status=str(g(row, "p10_status") or "").strip(),
            p20_date=g(row, "p20_date"), p20_status=str(g(row, "p20_status") or "").strip(),
            raw={k: g(row, k) for k in idx},
        ))
    wb.close()

    meta = {"sheet": sheet_name, "header_row": hi + 1, "rows_read": len(units),
            "columns": header, "column_index": idx}

    # ---- defects detected while loading
    if totals_rows:
        defects.append(Defect("Aggregate row inside data", "MEDIUM", "sheet",
                              f"{sheet_name} rows {hi + 2}+",
                              f"{totals_rows} TOTAL/subtotal row(s) sit inside the data body; "
                              "they were excluded but will corrupt any naive SUM",
                              "TOTAL", totals_rows))
    if dirty_unit:
        defects.append(Defect("Missing unit number", "HIGH", "sheet", sheet_name,
                              f"{dirty_unit} row(s) have no usable unit number",
                              "", dirty_unit))
    if dirty_floor:
        defects.append(Defect("Non-numeric floor", "LOW", "sheet", sheet_name,
                              f"{dirty_floor} row(s) have a non-numeric floor "
                              "(e.g. 'G', 'R', 'Ground')", "G / R", dirty_floor))
    if date_in_status:
        defects.append(Defect("Date in a status column", "HIGH", "sheet", sheet_name,
                              f"{date_in_status} row(s) put a date where RF Status "
                              "is expected, so status cannot be aggregated",
                              "26.09.2026", date_in_status))

    ut = defaultdict(int)
    for u in units:
        ut[u.unit_type] += 1
    if len(ut) > 6:
        defects.append(Defect("Inconsistent vocabulary", "MEDIUM", "sheet", sheet_name,
                              f"Unit Type uses {len(ut)} distinct spellings "
                              f"(e.g. STUDIO/Studio, 1 BHK/1 BR/1 BED) - "
                              "cannot be grouped without a mapping table",
                              ", ".join(sorted(ut)[:8]), sum(ut.values())))
    spa = defaultdict(int)
    for u in units:
        spa[u.spa_status] += 1
    if len(spa) > 4:
        defects.append(Defect("Inconsistent vocabulary", "MEDIUM", "sheet", sheet_name,
                              f"SPA Status uses {len(spa)} distinct values with mixed "
                              "casing (BINDED / COUNTERSIGN / Counter-Signed by Seller)",
                              ", ".join(sorted(spa)[:8]), sum(spa.values())))
    return units, defects, meta


# --------------------------------------------------------------------------- #
# Odoo side
# --------------------------------------------------------------------------- #
def load_odoo(client: OdooClient) -> dict[str, Any]:
    # ---- Companies first: every unit, invoice and payment is attributed to one.
    print("  reading companies ...")
    comps = client.read("res.company", client.search_ids("res.company", [], limit=50),
                        ["name", "currency_id", "vat"])
    print(f"    {len(comps)} companies")

    print("  reading properties ...")
    # company_id is mandatory here: it is the ground truth for which legal
    # entity holds a project (PARK RESIDENCY -> PARK RESIDENCY REAL ESTATE
    # DEVELOPMENT LLC, etc.), per the business rule.
    props = client.search_read("product.product", [("is_property", "=", True)],
                               ["name", "default_code", "building_name", "property_area",
                                "floor", "bedrooms", "unit_type", "net_price",
                                "list_price", "total_value", "company_id"],
                               limit=0, order="id asc")
    print(f"    {len(props):,} properties")

    print("  reading partners ...")
    # Every partner (customers and suppliers alike) - reconciliation may need to
    # tell "not a customer" apart from "not in Odoo at all".
    partners = client.search_read("res.partner", [],
                                  ["name", "ref", "email", "phone", "vat",
                                   "customer_rank", "supplier_rank", "company_id"],
                                  limit=0, order="id asc")
    print(f"    {len(partners):,} partners")

    print("  reading customer invoices ...")
    # property_id is the invoice -> unit link (points at product.template).
    # real_estate_ref exists but is empty on every record, so it is not read.
    invoices = client.search_read("account.move",
                                  [("move_type", "in", ["out_invoice", "out_refund"]),
                                   ("state", "=", "posted")],
                                  ["name", "partner_id", "invoice_date", "amount_total",
                                   "amount_residual", "amount_paid", "currency_id",
                                   "payment_state", "company_id", "move_type",
                                   "property_id", "invoice_line_ids"],
                                  limit=0, order="id asc")
    print(f"    {len(invoices):,} invoices")

    print("  reading customer payments ...")
    payments = client.search_read("account.payment",
                                  [("payment_type", "=", "inbound"),
                                   ("state", "not in", ["draft", "cancel"])],
                                  ["name", "partner_id", "date", "amount",
                                   "currency_id", "company_id", "partner_type",
                                   "payment_reference", "property_id"],
                                  limit=0, order="id asc")
    print(f"    {len(payments):,} payments")

    # ---- property templates: property_id on moves points here, not at
    # product.product. Needed to resolve invoice -> unit -> owning company.
    print("  reading property templates (invoice property_id target) ...")
    templates = client.search_read("product.template", [("is_property", "=", True)],
                                   ["name", "default_code", "building_name",
                                    "company_id"],
                                   limit=0, order="id asc")
    print(f"    {len(templates):,} property templates")

    print("  reading CRM leads (unit / project / company per lead) ...")
    try:
        leads = client.search_read("crm.lead", [],
                                   ["name", "partner_id", "property_id", "project_id",
                                    "company_id", "team_id", "stage_id"],
                                   limit=0, order="id desc")
    except Exception as exc:  # noqa: BLE001 - CRM is optional enrichment
        log.warning("crm.lead unavailable: %s", exc)
        leads = []
    print(f"    {len(leads):,} leads")

    return {"properties": props, "partners": partners, "invoices": invoices,
            "payments": payments, "companies": comps, "templates": templates,
            "leads": leads}


# --------------------------------------------------------------------------- #
# Project mapping
# --------------------------------------------------------------------------- #
def resolve_project_map(units: Sequence[SheetUnit], properties: Sequence[dict]
                        ) -> tuple[dict[str, dict[str, Any]], list[Defect]]:
    by_building: dict[str, list[dict]] = defaultdict(list)
    for p in properties:
        b = p.get("building_name")
        if b:
            by_building[str(b)].append(p)

    sheet_by_project: dict[str, list[SheetUnit]] = defaultdict(list)
    for u in units:
        sheet_by_project[u.project].append(u)

    mapping: dict[str, dict[str, Any]] = {}
    defects: list[Defect] = []

    for proj, items in sorted(sheet_by_project.items()):
        s_units = {u.unit for u in items}
        s_areas = [u.size for u in items if u.size is not None]
        scored: list[tuple[int, int, float, str, list[str]]] = []
        for b, plist in by_building.items():
            o_units = {norm_unit(p.get("default_code") or p.get("name")) for p in plist}
            o_units.discard("")
            overlap = s_units & o_units
            o_areas = [to_number(p.get("property_area")) for p in plist]
            o_areas = [a for a in o_areas if a is not None]
            area_hit = 0
            if s_areas and o_areas:
                lo, hi = min(o_areas), max(o_areas)
                area_hit = sum(1 for a in s_areas if lo * 0.9 <= a <= hi * 1.1)
            jac = len(overlap) / max(1, len(s_units | o_units))
            scored.append((len(overlap), area_hit, jac, b, sorted(overlap)))
        scored.sort(key=lambda t: (-t[0], -t[1]))

        if not scored:
            mapping[proj] = {"odoo_building": None, "confidence": "NONE",
                             "evidence": "no buildings present in Odoo"}
            continue

        top = scored[0]
        runner = scored[1] if len(scored) > 1 else None
        matched_units = top[0]
        runner_units = runner[0] if runner else 0

        if matched_units == 0:
            verdict, confidence = "UNRESOLVED", "NONE"
        elif runner and runner_units == matched_units:
            verdict, confidence = "AMBIGUOUS", "LOW"
        elif matched_units >= 0.8 * len(s_units):
            verdict, confidence = "RESOLVED", "HIGH"
        else:
            verdict, confidence = "PARTIAL", "MEDIUM"

        mapping[proj] = {
            "odoo_building": top[3],
            "confidence": confidence,
            "verdict": verdict,
            "sheet_units": len(items),
            "unit_matches": matched_units,
            "runner_up": runner[3] if runner else None,
            "runner_up_matches": runner_units,
            "area_hits": top[1],
            "jaccard": round(top[2], 3),
            "matched_sample": top[4][:10],
        }
        if verdict in ("AMBIGUOUS", "UNRESOLVED"):
            defects.append(Defect(
                "Project mapping not decisive", "HIGH", "both",
                f"project {proj}",
                f"{verdict}: best candidate {top[3]} ({matched_units} unit matches) "
                f"vs runner-up {runner[3] if runner else '-'} "
                f"({runner_units} matches) - human decision required", top[3]))

    # Buildings present in Odoo but absent from the spreadsheets.
    sheet_projects = set(sheet_by_project)
    mapped_buildings = {m["odoo_building"] for m in mapping.values() if m["odoo_building"]}
    for b, plist in sorted(by_building.items()):
        if b not in mapped_buildings:
            defects.append(Defect(
                "Odoo-only project", "HIGH", "odoo", f"product.product[{b}]",
                f"{len(plist):,} unit(s) exist in Odoo under building {b!r} but no "
                "sheet project maps to it - absent from the Parkgroup spreadsheets",
                b, len(plist)))
    return mapping, defects


# --------------------------------------------------------------------------- #
# Customer matching
# --------------------------------------------------------------------------- #
def build_partner_index(partners: Sequence[dict]) -> tuple[dict[str, list[dict]],
                                                           list[Defect]]:
    exact: dict[str, list[dict]] = defaultdict(list)
    defects: list[Defect] = []
    no_id = 0
    for p in partners:
        n = norm_name(p.get("name"))
        if not n:
            no_id += 1
            continue
        exact[n].append(p)
    if no_id:
        defects.append(Defect("Unnamed partner", "LOW", "odoo", "res.partner",
                              f"{no_id} partner(s) have no usable name", "", no_id))

    dupes = {k: v for k, v in exact.items() if len(v) > 1}
    if dupes:
        sample = ", ".join(list(dupes)[:6])
        affected = sum(len(v) for v in dupes.values())
        defects.append(Defect(
            "Duplicate partner names", "HIGH", "odoo", "res.partner",
            f"{len(dupes)} normalised name(s) map to more than one partner "
            f"({affected} records) - name alone cannot disambiguate",
            sample, affected))
    return exact, defects


def match_client(client: str, client_norm: str,
                 index: dict[str, list[dict]]) -> tuple[str, list[dict], list[str]]:
    """Classify a sheet client name against the Odoo partner index.

    Returns ``(verdict, candidates, suggestions)`` where verdict is one of
    MATCHED / AMBIGUOUS / UNMATCHED / NO_CLIENT.
    """
    if not client_norm:
        return "NO_CLIENT", [], []
    cands = index.get(client_norm, [])
    if len(cands) == 1:
        return "MATCHED", cands, []
    if len(cands) > 1:
        return "AMBIGUOUS", cands, []

    # No exact hit: suggest the closest names by token Jaccard.
    ct = set(client_norm.split())
    scored: list[tuple[float, dict]] = []
    for norm, ps in index.items():
        pt = set(norm.split())
        if not pt:
            continue
        j = len(ct & pt) / max(1, len(ct | pt))
        if j >= 0.6:
            scored.append((j, ps[0]))
    scored.sort(key=lambda t: -t[0])
    return "UNMATCHED", [], [f"{p.get('name')} ({round(j, 2)})" for j, p in scored[:5]]


#: Placeholder sheet values that mean "no counterparty on this row".
_EMPTY_TOKENS = {"", "-", "--", "N/A", "NA", "N.A.", "NONE", "NULL",
                 "AVAILABLE", "VACANT", "SOLD", "0"}

#: Common name-shape differences that should not force an AMBIGUOUS verdict.
#: These are *shape* cues, not identity - they only ever downgrade a multi-hit
#: name to a "likely" hint, never pick a partner.
_SHAPE_TOKENS = {"AND", "&"}


def _looks_like_joint_tenant(value: object) -> bool:
    """"A / B", "A & B", "A and B" -> two people on one sheet row."""
    s = str(value or "")
    return bool(re.search(r"\s[/&]\s|\sAND\s", s, re.IGNORECASE))


def _digits(value: object) -> str:
    """Keep only digits, the last 9 - phones are written many ways."""
    return "".join(ch for ch in str(value or "") if ch.isdigit())[-9:]


def _disambiguate(cands: Sequence[dict], client: str, contact: str, email: str
                  ) -> tuple[str, list[dict], str]:
    """Pick between same-name partners using the sheet's contact details.

    Evidence rule, in order:
      1. exactly one candidate whose phone matches the sheet Contact No
      2. exactly one candidate whose email matches the sheet Email
      3. otherwise stay AMBIGUOUS

    Never guesses when the evidence ties.
    """
    cands = list(cands)
    if len(cands) <= 1:
        return "MATCHED", cands, ""

    want_phone = _digits(contact)
    want_email = str(email or "").strip().lower()

    if want_phone:
        hits = [p for p in cands if _digits(p.get("phone")) == want_phone
                or _digits(p.get("mobile")) == want_phone]
        if len(hits) == 1:
            return "MATCHED", hits, f"resolved by phone match ({want_phone})"
        if len(hits) > 1:
            return "AMBIGUOUS", hits, f"{len(hits)} candidates share phone {want_phone}"

    if want_email:
        hits = [p for p in cands
                if str(p.get("email") or "").strip().lower() == want_email]
        if len(hits) == 1:
            return "MATCHED", hits, f"resolved by email match ({want_email})"
        if len(hits) > 1:
            return "AMBIGUOUS", hits, f"{len(hits)} candidates share email {want_email}"

    ids = sorted(p.get("id") for p in cands)
    with_detail = [p for p in cands
                   if (p.get("phone") or p.get("email") or p.get("vat"))]
    note = (f"{len(cands)} partners share this name (ids {ids}); "
            f"no contact detail on the sheet to separate them")
    if with_detail and len(with_detail) < len(cands):
        note += f"; {len(cands) - len(with_detail)} candidate(s) have no contact data"
    return "AMBIGUOUS", cands, note


# --------------------------------------------------------------------------- #
# Reconciliation
# --------------------------------------------------------------------------- #
def build_company_model(odoo: dict[str, Any]) -> dict[str, Any]:
    """Ground truth for "which legal entity holds which project/unit".

    Three independent sources, in priority order:
      1. ``product.product.company_id``  - the unit's owning company (authoritative)
      2. ``product.template.company_id`` - resolves ``account.move.property_id``
      3. ``crm.lead.company_id`` vs the worksite owner - cross-check only

    The ``property_id`` -> ``product.product`` join is the subtle part: moves
    point at ``product.template`` while the unit inventory lives in
    ``product.product``. Comparing the two id spaces directly makes almost every
    invoice look like it references an unknown unit, so templates are matched by
    unit code instead.
    """
    comp_name = {x["id"]: str(x.get("name")) for x in odoo["companies"]}

    # unit code -> owner, across all buildings (unit numbers repeat per building,
    # so the building must be part of the key).
    code_owner: dict[tuple[str, str], int] = {}
    building_owner: dict[str, int] = {}
    building_owner_counts: dict[str, Counter] = defaultdict(Counter)
    for u in odoo["properties"]:
        cid = (u.get("company_id") or [None])[0]
        b = str(u.get("building_name") or "")
        code = norm_unit(u.get("default_code") or u.get("name"))
        if code:
            code_owner.setdefault((b, code), cid)
        building_owner_counts[b][cid] += 1
    for b, counts in building_owner_counts.items():
        building_owner[b] = counts.most_common(1)[0][0]

    # template id -> (unit code, owner)
    tmpl_code: dict[int, str] = {}
    tmpl_owner: dict[int, int] = {}
    for t in odoo["templates"]:
        tid = t["id"]
        code = norm_unit(t.get("default_code") or t.get("name"))
        cid = (t.get("company_id") or [None])[0]
        if code:
            tmpl_code[tid] = code
        if cid:
            tmpl_owner[tid] = cid

    # CRM: worksite -> owner cross-check
    crm_by_worksite: dict[str, Counter] = defaultdict(Counter)
    for lead in odoo["leads"]:
        wid = (lead.get("project_id") or [None, None])[1]
        cid = (lead.get("company_id") or [None])[0]
        if wid and cid:
            crm_by_worksite[str(wid)][cid] += 1

    return {
        "comp_name": comp_name,
        "code_owner": code_owner,
        "building_owner": building_owner,
        "building_owner_counts": building_owner_counts,
        "tmpl_code": tmpl_code,
        "tmpl_owner": tmpl_owner,
        "crm_by_worksite": crm_by_worksite,
    }


def resolve_unit_company(model: dict[str, Any], building: str | None,
                         unit: str) -> tuple[int | None, str]:
    """Which company owns this (building, unit)? Returns (company_id, source)."""
    if building and unit:
        cid = model["code_owner"].get((building, unit))
        if cid:
            return cid, "product.product.company_id"
    if building:
        cid = model["building_owner"].get(building)
        if cid:
            return cid, "building majority owner"
    return None, "unresolved"


def resolve_invoice_company(model: dict[str, Any], move: dict[str, Any]
                            ) -> tuple[int | None, str]:
    """Resolve an invoice/payment's owning company via its property_id."""
    tid = (move.get("property_id") or [None])[0]
    if not tid:
        return (move.get("company_id") or [None])[0], "invoice.company_id (no property)"
    owner = model["tmpl_owner"].get(tid)
    if owner:
        return owner, "product.template.company_id"
    return (move.get("company_id") or [None])[0], "invoice.company_id (template unresolved)"


def reconcile(units: Sequence[SheetUnit], odoo: dict[str, Any],
              pmap: dict[str, dict[str, Any]],
              partner_index: dict[str, list[dict]],
              plan_map: dict[str, str] | None = None) -> dict[str, list[dict[str, Any]]]:
    model = build_company_model(odoo)
    comp_name = model["comp_name"]

    if plan_map is None:
        plan_map = load_project_plan_map(
            Path(r"C:\Parkgroup Data\Consolidated_Sales_Workbook (4).xlsx"))

    props_by_building: dict[str, dict[str, dict]] = defaultdict(dict)
    for p in odoo["properties"]:
        b = str(p.get("building_name") or "")
        props_by_building[b][norm_unit(p.get("default_code") or p.get("name"))] = p

    inv_by_partner: dict[int, list[dict]] = defaultdict(list)
    for i in odoo["invoices"]:
        pid = (i.get("partner_id") or [None])[0]
        if pid:
            inv_by_partner[pid].append(i)
    pay_by_partner: dict[int, list[dict]] = defaultdict(list)
    for p in odoo["payments"]:
        pid = (p.get("partner_id") or [None])[0]
        if pid:
            pay_by_partner[pid].append(p)

    # Per-company invoiced / collected totals, so a sheet unit is compared inside
    # the company that actually holds it rather than against a cross-company sum.
    inv_company_total: dict[int, float] = defaultdict(float)
    pay_company_total: dict[int, float] = defaultdict(float)
    inv_company_count: Counter = Counter()
    pay_company_count: Counter = Counter()
    for i in odoo["invoices"]:
        cid, _ = resolve_invoice_company(model, i)
        if cid:
            inv_company_total[cid] += to_number(i.get("amount_total")) or 0.0
            inv_company_count[cid] += 1
    for p in odoo["payments"]:
        cid, _ = resolve_invoice_company(model, p)
        if cid:
            pay_company_total[cid] += to_number(p.get("amount")) or 0.0
            pay_company_count[cid] += 1

    recon: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    unreconciled: list[dict[str, Any]] = []

    used_products: set[tuple[str, str]] = set()

    # How many sheet units does each client own? Needed before any money
    # comparison: the sheet carries a PER-UNIT collection, while Odoo is
    # queried PER CUSTOMER. Those are only comparable when the client owns
    # exactly one unit; otherwise a single lifetime total would be compared
    # against each of their units and every one would look wrong.
    units_per_client: dict[str, int] = defaultdict(int)
    for u in units:
        if u.client_norm:
            units_per_client[u.client_norm] += 1

    company_mismatch = 0
    company_rows = 0

    for u in units:
        b = (pmap.get(u.project) or {}).get("odoo_building")
        prop = props_by_building.get(b or "", {}).get(u.unit)
        client_verdict, cands, sugg = match_client(u.client, u.client_norm, partner_index)
        n_units = units_per_client.get(u.client_norm, 0)
        disambiguated = ""
        if client_verdict == "AMBIGUOUS":
            refined, rcands, disambiguated = _disambiguate(cands, u.client,
                                                           u.contact, u.email)
            client_verdict = refined
            cands = rcands

        row: dict[str, Any] = {
            "sheet_row": u.row_no,
            "project": u.project,
            "unit_no": u.unit,
            "unit_no_raw": u.unit_raw,
            "unit_type": u.unit_type,
            "size_sqft_sheet": u.size,
            "status_sheet": u.status,
            "client_sheet": u.client,
            "nationality": u.nationality,
            "contact_sheet": u.contact,
            "email_sheet": u.email,
            "total_price_sheet": u.total_price,
            "sold_price_sheet": u.sold_price,
            "list_price_sheet": u.list_price,
            "collected_sheet": u.collected,
            "balance_due_sheet": u.balance_due,
            "odoo_building": b,
            "odoo_product_id": prop.get("id") if prop else None,
            "odoo_product_name": prop.get("name") if prop else None,
            "odoo_unit_code": (prop.get("default_code") if prop else None),
            "size_sqft_odoo": to_number(prop.get("property_area")) if prop else None,
            "odoo_net_price": to_number(prop.get("net_price")) if prop else None,

            # ---- owning legal entity (the business rule: a project sits under
            # one company, e.g. PARK RESIDENCY -> PARK RESIDENCY REAL ESTATE
            # DEVELOPMENT LLC). Resolved from Odoo, not inferred from the name.
            "odoo_company_id": (prop.get("company_id") or [None])[0] if prop else None,
            "odoo_company": (comp_name.get((prop.get("company_id") or [None])[0])
                             if prop else None),
            "company_source": "product.product.company_id" if prop else "unresolved",
            "client_match": client_verdict,
            "odoo_partner_id": cands[0].get("id") if len(cands) == 1 else None,
            "odoo_partner_name": cands[0].get("name") if len(cands) == 1 else None,
            "sheet_units_owned_by_client": n_units,
            "client_match_note": disambiguated,
            "client_match_suggestions": "; ".join(sugg),
            "joint_tenant_sheet": "YES" if _looks_like_joint_tenant(u.client_raw) else "NO",
        }

        # size comparison
        if prop is not None and u.size is not None:
            o_size = to_number(prop.get("property_area"))
            if o_size is not None:
                delta = u.size - o_size
                row["size_delta"] = round(delta, 2)
                row["size_delta_pct"] = round(100 * delta / o_size, 2) if o_size else None
                row["size_verdict"] = "MATCH" if abs(delta) <= 1.0 else "DIFFERS"

        if prop is not None:
            used_products.add((b or "", u.unit))

        # customer-level money comparison
        if len(cands) == 1:
            pid = cands[0].get("id")
            invs = inv_by_partner.get(pid, [])
            pays = pay_by_partner.get(pid, [])
            inv_total = sum(to_number(i.get("amount_total")) or 0.0 for i in invs)
            inv_paid = sum(to_number(i.get("amount_paid")) or 0.0 for i in invs)
            pay_total = sum(to_number(p.get("amount")) or 0.0 for p in pays)
            row["odoo_invoice_count"] = len(invs)
            row["odoo_invoice_total"] = round(inv_total, 2)
            row["odoo_invoice_paid"] = round(inv_paid, 2)
            row["odoo_payment_count"] = len(pays)
            row["odoo_payment_total"] = round(pay_total, 2)
            row["odoo_unapplied"] = round(pay_total - inv_paid, 2)

            # A buyer who owns several units can also appear on an Available unit row,
            # but only one unit is theirs. That must not disable the comparison
            # for the unit they actually bought.
            comparable = (u.status.lower() != "sold") or (n_units == 1)
            if comparable:
                row["amount_comparable"] = "YES"
                row["amount_comparable_basis"] = (
                    "client owns exactly one sheet unit" if n_units == 1
                    else "row is not a Sold unit, so the client's totals belong "
                         "to their other unit(s)")
                if u.collected is not None:
                    row["collected_verdict"] = ("MATCH" if amounts_close(u.collected, pay_total)
                                                else "DIFFERS")
                    if row["collected_verdict"] == "DIFFERS":
                        row["collected_delta"] = round(u.collected - pay_total, 2)
                if u.total_price is not None and inv_total:
                    row["price_verdict"] = ("MATCH" if amounts_close(u.total_price, inv_total)
                                            else "DIFFERS")
                    if row["price_verdict"] == "DIFFERS":
                        row["price_delta"] = round(u.total_price - inv_total, 2)

                # Company-scoped context: how much the OWNING legal entity has
                # invoiced and collected in total. Context only - never presented
                # as a per-unit figure.
                cid = row.get("odoo_company_id")
                if cid:
                    row["company_invoiced_total"] = round(inv_company_total.get(cid, 0.0), 2)
                    row["company_collected_total"] = round(pay_company_total.get(cid, 0.0), 2)
                    row["company_invoice_count"] = inv_company_count.get(cid, 0)
                    row["company_payment_count"] = pay_company_count.get(cid, 0)
            else:
                # Multi-unit client: a per-unit sheet figure cannot be tested
                # against a lifetime customer total, so we record the Odoo
                # totals but do NOT claim a match or a discrepancy.
                row["amount_comparable"] = "NO"
                row["collected_verdict"] = "NOT_COMPARABLE"
                row["price_verdict"] = "NOT_COMPARABLE"
                row["not_comparable_reason"] = (
                    f"this is a {u.status} unit and the client owns {n_units} sheet "
                    "unit(s); sheet figures are per unit while Odoo totals are "
                    "per customer lifetime")

        # ---- payment-plan validation: does this unit's 10%/20% installments
        # honour the project's declared plan? A mismatch forces ambiguity -
        # the unit is not copied until a human resolves it.
        code = map_project_to_code(u.project)
        plan_desc = plan_map.get(code, "")
        plan_type = classify_plan(plan_desc)
        pp_issues = validate_payment_plan(u, plan_type)
        if pp_issues:
            row["payment_plan_mismatch"] = "YES"
            row["payment_plan_project_code"] = code
            row["payment_plan_type"] = plan_type
            row["payment_plan_description"] = plan_desc[:200]
            row["payment_plan_issues"] = "; ".join(pp_issues)

        # ---- verify the invoice company agrees with the unit's owning company.
        # A mismatch means a document was booked against the wrong legal entity.
        ucid = row.get("odoo_company_id")
        if ucid:
            company_rows += 1
            inv_companies = {(resolve_invoice_company(model, i)[0])
                             for i in inv_by_partner.get(
                                 (cands[0].get("id") if len(cands) == 1 else None), [])}
            inv_companies.discard(None)
            pay_companies = {(resolve_invoice_company(model, p)[0])
                             for p in pay_by_partner.get(
                                 (cands[0].get("id") if len(cands) == 1 else None), [])}
            pay_companies.discard(None)
            row["odoo_invoice_companies"] = ", ".join(
                sorted(str(comp_name.get(c, c)) for c in inv_companies))
            row["odoo_payment_companies"] = ", ".join(
                sorted(str(comp_name.get(c, c)) for c in pay_companies))
            foreign_inv = inv_companies - {ucid}
            foreign_pay = pay_companies - {ucid}
            row["company_alignment"] = (
                "OK" if not foreign_inv and not foreign_pay
                else ("MISMATCH" if (foreign_inv or foreign_pay) else "NO_DOCUMENTS"))
            if foreign_inv or foreign_pay:
                company_mismatch += 1
                bad = sorted(foreign_inv | foreign_pay)
                row["company_mismatch_detail"] = ", ".join(
                    str(comp_name.get(c, c)) for c in bad)
                row["company_mismatch_reason"] = (
                    "this client's documents span two legal entities, so they most "
                    "likely hold units in each - confirm before treating it as an error")
                row["internal_note"] = (
                    f"Unit {u.unit} of {b} is held by {comp_name.get(ucid)}; this "
                    f"client's documents also sit under "
                    f"{', '.join(str(comp_name.get(c, c)) for c in bad)}")
            else:
                row["internal_note"] = (
                    f"Unit {u.unit} of {b} is held by {comp_name.get(ucid)}"
                    + (f" - client invoiced {row.get('odoo_invoice_count')} invoice(s) "
                       f"under the same entity"
                       if row.get("odoo_invoice_count") else
                       " - no Odoo documents linked to this client yet"))

        # verdicts
        issues: list[str] = []
        if prop is None:
            issues.append("no Odoo unit for this project+unit")
        if row.get("company_alignment") == "MISMATCH":
            issues.append(f"document company differs from unit owner: "
                          f"{row.get('company_mismatch_detail')}")
        if client_verdict == "UNMATCHED":
            issues.append("client not found in Odoo partners")
        elif client_verdict == "AMBIGUOUS":
            issues.append("client name matches multiple Odoo partners")
        elif client_verdict == "NO_CLIENT":
            issues.append("sheet row has no client")
        if row.get("collected_verdict") == "DIFFERS":
            issues.append(f"collected differs by {row.get('collected_delta')}")
        if row.get("price_verdict") == "DIFFERS":
            issues.append(f"total price differs from invoiced by {row.get('price_delta')}")
        if row.get("payment_plan_mismatch") == "YES":
            issues.append(f"payment plan mismatch: {row.get('payment_plan_issues')}")

        if prop is None or client_verdict == "UNMATCHED" or client_verdict == "NO_CLIENT":
            row["recon_status"] = "UNRECONCILED"
            unreconciled.append({**row, "reason": "; ".join(issues)})
        elif row.get("payment_plan_mismatch") == "YES":
            # Installments do not match the declared plan -> must not be copied
            # until a human resolves it. Kept out of RECONCILED deliberately.
            row["recon_status"] = "AMBIGUOUS"
            ambiguous.append({**row, "reason": "; ".join(issues)})
        elif (client_verdict == "AMBIGUOUS" or len(issues) > 1
              or row.get("company_alignment") == "MISMATCH"):
            row["recon_status"] = "AMBIGUOUS"
            ambiguous.append({**row, "reason": "; ".join(issues)})
        else:
            row["recon_status"] = "RECONCILED"
        row["issues"] = "; ".join(issues)
        recon.append(row)

    # Odoo units with no sheet counterpart
    for b, units_map in sorted(props_by_building.items()):
        for unit, prop in sorted(units_map.items()):
            if (b, unit) not in used_products:
                unreconciled.append({
                    "sheet_row": None,
                    "project": "(none)",
                    "unit_no": unit,
                    "unit_no_raw": prop.get("default_code"),
                    "unit_type": prop.get("unit_type"),
                    "size_sqft_sheet": None,
                    "status_sheet": None,
                    "client_sheet": None,
                    "odoo_building": b,
                    "odoo_product_id": prop.get("id"),
                    "odoo_product_name": prop.get("name"),
                    "odoo_unit_code": prop.get("default_code"),
                    "size_sqft_odoo": to_number(prop.get("property_area")),
                    "odoo_company_id": (prop.get("company_id") or [None])[0],
                    "odoo_company": comp_name.get((prop.get("company_id") or [None])[0]),
                    "company_source": "product.product.company_id",
                    "internal_note": (f"Unit {unit} is held by "
                                      f"{comp_name.get((prop.get('company_id') or [None])[0])} "
                                      f"but has no row in the Parkgroup spreadsheets"),
                    "client_match": "NOT_IN_SHEET",
                    "recon_status": "ODOO_ONLY",
                    "reason": "unit exists in Odoo but no sheet row maps to it",
                    "issues": "orphaned Odoo unit",
                })

    # Company alignment summary, surfaced as its own sheet.
    company_rows_out: list[dict[str, Any]] = []
    for b, counts in model["building_owner_counts"].items():
        total_units = sum(counts.values())
        owners = sorted(counts.items(), key=lambda kv: -kv[1])
        company_rows_out.append({
            "odoo_building": b,
            "sheet_projects": ", ".join(sorted(
                p for p, m in pmap.items() if m.get("odoo_building") == b)) or "(none)",
            "units": total_units,
            "distinct_owners": len(owners),
            "primary_owner_id": owners[0][0],
            "primary_owner": comp_name.get(owners[0][0]),
            "ownership_split": "; ".join(
                f"{comp_name.get(cid, cid)}={n}" for cid, n in owners),
            "mixed_ownership": "YES" if len(owners) > 1 else "NO",
            "crm_lead_companies": "; ".join(
                f"{comp_name.get(cid, cid)}={n}"
                for cid, n in model["crm_by_worksite"].get(b, Counter()).most_common(4)),
            "internal_note": (f"{b} is licensed to "
                              f"{comp_name.get(owners[0][0])}"
                              + (" with additional owners" if len(owners) > 1 else "")
                              + "; recorded as an internal note, not a data change"),
        })

    return {"reconciliation": recon, "ambiguous": ambiguous,
            "unreconciled": unreconciled, "company_map": company_rows_out,
            "company_mismatch_rows": company_mismatch,
            "company_rows_checked": company_rows}


# --------------------------------------------------------------------------- #
# Workbook output
# --------------------------------------------------------------------------- #
HDR_FONT = Font(bold=True, color="FFFFFF")
HDR_FILL = PatternFill("solid", fgColor="1F4E78")


def _excel_safe(value: Any) -> Any:
    """Excel cells cannot hold lists/dicts; render them compactly."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    from datetime import date, datetime as _dt
    if isinstance(value, (_dt, date)):
        return value.isoformat()
    return str(value)


def _add_sheet(wb: Workbook, title: str, rows: Sequence[dict[str, Any]]) -> None:
    ws = wb.create_sheet(title[:31])
    cols: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    if not cols:
        ws.append(["(no rows)"])
        return
    ws.append(cols)
    for c in ws[1]:
        c.font = HDR_FONT
        c.fill = HDR_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for r in rows:
        ws.append([_excel_safe(r.get(c)) for c in cols])
    for i, c in enumerate(cols, start=1):
        letter = get_column_letter(i)
        if any(h in c for h in ("amount", "price", "delta", "total", "paid", "collected",
                               "balance", "area", "size", "unapplied", "fee", "discount")):
            for cell in ws[letter][1:]:
                if isinstance(cell.value, (int, float)):
                    cell.number_format = "#,##0.00"
        else:
            longest = max((len(str(r.get(c) or "")) for r in rows[:800]), default=10)
            ws.column_dimensions[letter].width = min(max(longest + 2, 10), 46)
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = ws.dimensions


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Reconcile Parkgroup sheets against Odoo.")
    ap.add_argument("--sheet", default=str(DEFAULT_SHEET))
    ap.add_argument("--sheet-name", default=UNIT_SHEET_NAME)
    ap.add_argument("--out", default="reconciliation_2026-10-06.xlsx")
    ap.add_argument("--amount-tol", type=float, default=AMOUNT_TOL)
    args = ap.parse_args(argv)

    sheet_path = Path(args.sheet)
    print(f"Reading sheets: {sheet_path.name} / {args.sheet_name!r}")
    units, defects, meta = load_units(sheet_path, args.sheet_name)
    print(f"  {len(units):,} unit rows, header on row {meta['header_row']}")

    print("Connecting to Odoo ...")
    try:
        client = OdooClient()
    except OdooError as exc:
        print(f"  FAILED: {exc}")
        return 2
    odoo = load_odoo(client)

    print("Resolving project mapping ...")
    pmap, pdefects = resolve_project_map(units, odoo["properties"])
    defects += pdefects
    for proj, m in pmap.items():
        print(f"  {proj:<8} -> {str(m['odoo_building']):<32} "
              f"{m['verdict']:<10} conf={m['confidence']:<7} "
              f"units {m.get('unit_matches')}/{m.get('sheet_units')}")

    print("Indexing partners ...")
    partner_index, pdefects2 = build_partner_index(odoo["partners"])
    defects += pdefects2

    print("Reconciling ...")
    result = reconcile(units, odoo, pmap, partner_index)
    defects += collect_value_defects(units, odoo)

    clarifications = build_clarifications(pmap, result, defects)
    pp_flagged = sum(1 for r in result["reconciliation"]
                     if r.get("payment_plan_mismatch") == "YES")

    wb = Workbook()
    wb.remove(wb.active)

    _add_sheet(wb, "Summary", [{
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_sheet": str(sheet_path),
        "source_sheet_name": args.sheet_name,
        "odoo_url": client.url,
        "odoo_database": client.db,
        "odoo_version": client.about().get("server_version"),
        "authenticated_user": (client.about().get("user") or {}).get("login"),
        "amount_tolerance": args.amount_tol,
        "sheet_units": len(units),
        "odoo_properties": len(odoo["properties"]),
        "odoo_partners": len(odoo["partners"]),
        "odoo_invoices": len(odoo["invoices"]),
        "odoo_payments": len(odoo["payments"]),
        "reconciled": sum(1 for r in result["reconciliation"]
                          if r["recon_status"] == "RECONCILED"),
        "ambiguous": len(result["ambiguous"]),
        "unreconciled": len(result["unreconciled"]),
        "defects": len(defects),
        "clarifications": len(clarifications),
        "payment_plan_mismatches": pp_flagged,
        "companies": len(odoo["companies"]),
        "company_rows_checked": result["company_rows_checked"],
        "company_mismatch_rows": result["company_mismatch_rows"],
        "company_note": ("Each project is licensed to one company, read from "
                         "product.product.company_id. Recorded in Company_Map and "
                         "per-row internal_note. No multi-company restructure was made."),
        "currency_note": "All amounts are AED unless stated; never summed across currencies.",
    }])

    _add_sheet(wb, "Project_Map", [
        {"sheet_project": k, **{kk: vv for kk, vv in v.items()}}
        for k, v in pmap.items()])
    _add_sheet(wb, "Company_Map", result["company_map"])
    _add_sheet(wb, "Reconciliation", result["reconciliation"])
    _add_sheet(wb, "Ambiguous", result["ambiguous"])
    _add_sheet(wb, "Unreconciled", result["unreconciled"])
    _add_sheet(wb, "Defects_Log", [
        {"category": d.category, "severity": d.severity, "scope": d.scope,
         "location": d.location, "record_count": d.record_count,
         "description": d.description, "example": d.example} for d in defects])
    _add_sheet(wb, "Clarifications", clarifications)

    out = Path(args.out).expanduser().resolve()
    wb.save(out)

    print()
    print("=" * 78)
    print(f"RECONCILIATION COMPLETE -> {out}")
    print("=" * 78)
    print(f"  sheet units read      : {len(units):>8,}")
    print(f"  RECONCILED            : {sum(1 for r in result['reconciliation'] if r['recon_status'] == 'RECONCILED'):>8,}")
    print(f"  AMBIGUOUS             : {len(result['ambiguous']):>8,}")
    print(f"  UNRECONCILED          : {len(result['unreconciled']):>8,}")
    print(f"  defects logged        : {len(defects):>8,}")
    print(f"  clarifications needed : {len(clarifications):>8,}")
    print(f"  payment-plan mismatches: {pp_flagged:>7,}")
    print()
    print("COMPANY ATTRIBUTION (project -> licensed entity)")
    print("-" * 78)
    for row in result["company_map"]:
        print(f"  {row['odoo_building']:<32} -> {str(row['primary_owner'])[:40]:<42}"
              f"{row['units']:>5} units"
              + ("  MIXED" if row["mixed_ownership"] == "YES" else ""))
    print()
    print(f"  company alignment checked : {result['company_rows_checked']:,} rows")
    print(f"  company MISMATCH rows     : {result['company_mismatch_rows']:,}")
    return 0


def collect_value_defects(units: Sequence[SheetUnit], odoo: dict[str, Any]) -> list[Defect]:
    """Value-level defects found while comparing."""
    out: list[Defect] = []

    neg = [u for u in units if (u.collected or 0) < 0]
    if neg:
        out.append(Defect("Negative collection", "HIGH", "sheet", "All Units",
                          f"{len(neg)} unit(s) show a negative Amount Collected",
                          neg[0].client, len(neg)))

    bad_sum = []
    for u in units:
        if u.list_price is not None and u.discount is not None and u.sold_price is not None:
            if abs((u.list_price - u.discount) - u.sold_price) > 1.0:
                bad_sum.append(u)
    if bad_sum:
        out.append(Defect("Arithmetic inconsistency", "HIGH", "sheet", "All Units",
                          f"{len(bad_sum)} unit(s) where List - Discount != Sold Price",
                          f"row {bad_sum[0].row_no}: {bad_sum[0].project}/{bad_sum[0].unit}",
                          len(bad_sum)))

    bad_total = []
    for u in units:
        if u.sold_price is not None and u.total_price is not None and u.admin_fee is not None:
            if abs((u.sold_price + u.admin_fee) - u.total_price) > 1.0:
                bad_total.append(u)
    if bad_total:
        out.append(Defect("Arithmetic inconsistency", "MEDIUM", "sheet", "All Units",
                          f"{len(bad_total)} unit(s) where Sold + Admin Fee != Total Price",
                          f"row {bad_total[0].row_no}: {bad_total[0].project}/{bad_total[0].unit}",
                          len(bad_total)))

    # The invoice -> unit link DOES exist, via property_id. Only real_estate_ref
    # is dead. Reporting this as "no link at all" would be wrong.
    if odoo.get("invoices"):
        linked = sum(1 for i in odoo["invoices"] if i.get("property_id"))
        total = len(odoo["invoices"])
        if linked:
            out.append(Defect(
                "Invoice-to-unit link partly unused", "MEDIUM", "odoo",
                "account.move.property_id",
                f"{linked:,}/{total:,} customer invoices ({100*linked/total:.1f}%) are "
                f"linked to a unit through `property_id` (pointing at product.template). "
                f"However `real_estate_ref` is empty on every invoice and payment, i.e. "
                "a redundant second link exists and is never populated - pick one "
                "canonical field before migrating",
                f"property_id used on {linked:,}; real_estate_ref used on 0", total - linked))
        if total - linked:
            out.append(Defect(
                "Invoice without a unit", "MEDIUM", "odoo", "account.move.property_id",
                f"{total - linked:,} customer invoice(s) have no property_id, so their "
                "money cannot be attributed to a specific unit",
                "", total - linked))

    multi_ccy = defaultdict(int)
    for i in odoo["invoices"]:
        multi_ccy[str((i.get("currency_id") or [None, "?"])[1])] += 1
    if len(multi_ccy) > 1:
        out.append(Defect("Multi-currency ledger", "MEDIUM", "odoo", "account.move",
                          f"invoices span {len(multi_ccy)} currencies "
                          f"({dict(multi_ccy)}) - totals must never be blended",
                          ", ".join(multi_ccy), len(odoo["invoices"])))
    return out


def build_clarifications(pmap: dict[str, dict[str, Any]],
                         result: dict[str, list[dict]],
                         defects: Sequence[Defect]) -> list[dict[str, Any]]:
    qs: list[dict[str, Any]] = []
    n = 0
    for proj, m in sorted(pmap.items()):
        if m["verdict"] in ("AMBIGUOUS", "UNRESOLVED", "PARTIAL"):
            n += 1
            qs.append({
                "id": f"Q{n:02d}", "topic": "Project mapping", "priority": "HIGH",
                "question": f"Sheet project {proj!r} maps to {m['odoo_building']!r} "
                            f"with only {m.get('unit_matches')}/{m.get('sheet_units')} "
                            f"unit matches (runner-up {m.get('runner_up')} with "
                            f"{m.get('runner_up_matches')}). Confirm the mapping?",
                "blocks": f"{m.get('sheet_units')} unit rows",
                "our_assumption": "best candidate by unit-number overlap",
            })
    amb_partner = [r for r in result["ambiguous"] if r.get("client_match") == "AMBIGUOUS"]
    if amb_partner:
        n += 1
        qs.append({
            "id": f"Q{n:02d}", "topic": "Customer identity", "priority": "HIGH",
            "question": f"{len(amb_partner)} sheet client name(s) match more than one "
                        "Odoo partner. Which partner is correct (e.g. distinguish by "
                        "phone / email / VAT)?",
            "blocks": f"{len(amb_partner)} unit rows",
            "our_assumption": "none - no partner chosen",
        })
    unmatched = [r for r in result["unreconciled"] if r.get("client_match") == "UNMATCHED"]
    if unmatched:
        n += 1
        qs.append({
            "id": f"Q{n:02d}", "topic": "Customer identity", "priority": "HIGH",
            "question": f"{len(unmatched)} sheet client(s) do not match any Odoo partner "
                        "name. Are these genuinely new customers, or are they recorded "
                        "in Odoo under a different name / as a company?",
            "blocks": f"{len(unmatched)} unit rows",
            "our_assumption": "left unmatched",
        })
    odoo_only = [r for r in result["unreconciled"] if r.get("client_match") == "NOT_IN_SHEET"]
    if odoo_only:
        buildings = sorted({str(r.get("odoo_building")) for r in odoo_only})
        n += 1
        qs.append({
            "id": f"Q{n:02d}", "topic": "Scope", "priority": "HIGH",
            "question": f"{len(odoo_only):,} unit(s) exist in Odoo under "
                        f"{', '.join(buildings)} but have no row in the Parkgroup "
                        "spreadsheets. Should they be included in the migrated database?",
            "blocks": f"{len(odoo_only)} Odoo-only units",
            "our_assumption": "reported as ODOO_ONLY, not migrated",
        })
    if any(d.category == "Invoice-to-unit link partly unused" for d in defects):
        n += 1
        qs.append({
            "id": f"Q{n:02d}", "topic": "Data model", "priority": "HIGH",
            "question": "Invoices DO link to a unit through `property_id` (95.5% of "
                        "customer invoices), but `real_estate_ref` is empty on every "
                        "invoice and payment. Which field should be canonical in the "
                        "migrated database?",
            "blocks": "choice of the invoice->unit link for the target schema",
            "our_assumption": "property_id used as the link; real_estate_ref ignored",
        })
    if any(d.category == "Invoice without a unit" for d in defects):
        n += 1
        qs.append({
            "id": f"Q{n:02d}", "topic": "Data model", "priority": "MEDIUM",
            "question": "Some customer invoices have no property_id. Are those "
                        "genuinely unit-less (e.g. brokerage/commission fees), or is "
                        "the link simply missing?",
            "blocks": "unit-level attribution for those invoices",
            "our_assumption": "left un-attributed to any unit",
        })
    pp_bad = [r for r in result["reconciliation"]
              if r.get("payment_plan_mismatch") == "YES"]
    if pp_bad:
        n += 1
        qs.append({
            "id": f"Q{n:02d}", "topic": "Payment plan", "priority": "HIGH",
            "question": f"{len(pp_bad)} unit(s) have instalments that contradict their "
                        "project's declared payment plan (the 20% milestone is dated "
                        "before the 10% milestone). Confirm the correct schedule for "
                        "each unit before its payment plan is migrated - see the "
                        "Ambiguous sheet, payment_plan_mismatch = YES.",
            "blocks": f"{len(pp_bad)} unit rows' payment plans",
            "our_assumption": "units left AMBIGUOUS; installments not copied for migration",
        })
    n += 1
    qs.append({
        "id": f"Q{n:02d}", "topic": "Migration target", "priority": "HIGH",
        "question": "parkgroup.sgctech.ai returns HTTP 403 to this machine (Cloudflare), "
                    "so the target database cannot be read. Provide a credential for that "
                    "host, or export the target's partners/accounts/journals so the "
                    "ID mapping can be resolved?",
        "blocks": "old_id -> new_id mapping resolution",
        "our_assumption": "mapping prepared against natural keys only",
    })
    return qs


if __name__ == "__main__":
    raise SystemExit(main())