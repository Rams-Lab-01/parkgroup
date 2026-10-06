"""Build the old_id -> new_id mapping between pgre.odoo.com (migration_out)
and the PARK Group target instance (target_out).

Entities: companies, journals, accounts, partners (the reference tables the
20 migration datasets point at).  Matching is evidence-based and reports its
method + confidence:

  companies  name       all old companies -> the single target company
  journals   code       exact code match, then name, then type suggestion
  accounts   code/name  code rarely coincides (different charts!) -> name
  partners   name       normalized-name match (reconcile.norm_name), then
                        email, then VAT; ambiguity is reported, never guessed

Outputs: target_mapping_2026-10-06.xlsx (report) + .json (machine-readable
old_id -> new_id per entity, for the migration importer).
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook

ROOT = Path(r"C:\Parkgroup Data\odoo_mcp")
sys.path.insert(0, str(ROOT))
from reconcile import _add_sheet, norm_name  # noqa: E402

OLD = ROOT / "migration_out"
NEW = ROOT / "target_out"
OUT_XLSX = ROOT / "target_mapping_2026-10-06.xlsx"
OUT_JSON = ROOT / "target_mapping_2026-10-06.json"


def load(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def s(value: object) -> str:
    if value in (None, "", "False", "None"):
        return ""
    return str(value).strip()


def b(value: object) -> bool:
    return s(value).lower() == "true"


def main() -> int:
    old_comp = load(OLD / "companies.csv")
    old_jour = load(OLD / "journals.csv")
    old_acc = load(OLD / "accounts.csv")
    old_part = load(OLD / "partners.csv")
    new_comp = load(NEW / "companies.csv")
    new_jour = load(NEW / "journals.csv")
    new_acc = load(NEW / "accounts.csv")
    new_part = load(NEW / "partners.csv")

    mapping: dict[str, dict[str, dict]] = {
        "companies": {}, "journals": {}, "accounts": {}, "partners": {}}
    rows: dict[str, list[dict]] = {
        "Companies": [], "Journals": [], "Accounts": [], "Partners": []}

    # ---- companies: everything maps to the single target company -----------
    target_company = new_comp[0]
    for r in old_comp:
        exact = s(r.get("name")) == s(target_company["name"])
        rows["Companies"].append({
            "old_id": r.get("old_id"), "old_name": s(r.get("name")),
            "new_id": target_company["id"], "new_name": s(target_company["name"]),
            "method": "name-exact" if exact else "single-target-company",
            "note": "" if exact else "7 old companies collapse into the 1 target "
                                     "company; old attribution goes to internal notes",
        })
        mapping["companies"][r["old_id"]] = {
            "new_id": int(target_company["id"]), "method": "single-target-company"}

    # ---- journals: code -> name -> type suggestion -------------------------
    by_code: dict[str, list[dict]] = defaultdict(list)
    by_name: dict[str, list[dict]] = defaultdict(list)
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in new_jour:
        by_code[s(r.get("code")).upper()].append(r)
        by_name[norm_name(s(r.get("name")))].append(r)
        by_type[s(r.get("type"))].append(r)
    for r in old_jour:
        code, name = s(r.get("code")).upper(), norm_name(s(r.get("name")))
        cands = by_code.get(code) or []
        method = "code"
        if not cands:
            cands, method = by_name.get(name) or [], "name"
        if not cands and len(by_type.get(s(r.get("type"))) or []) == 1:
            cands, method = by_type[s(r.get("type"))], "type-only-suggestion"
        target = cands[0] if cands else None
        rows["Journals"].append({
            "old_id": r.get("old_id"), "old_company": s(r.get("company_id")),
            "old_code": s(r.get("code")), "old_name": s(r.get("name")),
            "old_type": s(r.get("type")),
            "new_id": target["id"] if target else "",
            "new_code": s(target.get("code")) if target else "",
            "new_name": s(target.get("name")) if target else "",
            "method": method if target else "",
            "status": "MATCHED" if target else "UNMATCHED",
        })
        if target:
            mapping["journals"][r["old_id"]] = {
                "new_id": int(target["id"]), "method": method}

    # ---- accounts: name is the meaning; code only when both agree ----------
    # The two charts reuse numeric ranges with DIFFERENT meanings (e.g. old
    # 400043 "Income Tax" vs new 400043 "Security & Guard"), so a code match
    # without a name match is reported for review, never auto-mapped.
    acc_by_code: dict[str, list[dict]] = defaultdict(list)
    acc_by_name: dict[str, list[dict]] = defaultdict(list)
    for r in new_acc:
        acc_by_code[s(r.get("code")).upper()].append(r)
        acc_by_name[norm_name(s(r.get("name")))].append(r)
    for r in old_acc:
        code, name = s(r.get("code")).upper(), norm_name(s(r.get("name")))
        code_c = acc_by_code.get(code) or []
        name_c = acc_by_name.get(name) or []
        target, method, note = None, "", ""
        if code_c and any(norm_name(s(c.get("name"))) == name for c in code_c):
            target = [c for c in code_c if norm_name(s(c.get("name"))) == name][0]
            method = "code+name"
        elif name_c:
            pick = name_c
            typed = [c for c in pick
                     if s(c.get("account_type")) == s(r.get("account_type"))]
            if typed:
                pick = typed
            target = pick[0]
            method = "name" if len(pick) == 1 else "name-first-of-many"
        elif code_c:
            method = "code-only-suspect"
            note = (f"same code but different meaning: "
                    f"{s(code_c[0].get('code'))} is {s(code_c[0].get('name'))!r} "
                    f"in the target - confirm before mapping")
        if target is None and method != "code-only-suspect":
            method = ""
        rows["Accounts"].append({
            "old_id": r.get("old_id"), "old_company": s(r.get("company_id")),
            "old_code": s(r.get("code")), "old_name": s(r.get("name")),
            "old_type": s(r.get("account_type")),
            "new_id": target["id"] if target else "",
            "new_code": s(target.get("code")) if target else "",
            "new_name": s(target.get("name")) if target else "",
            "method": method,
            "status": ("MATCHED" if target else
                       "REVIEW" if method == "code-only-suspect" else "UNMATCHED"),
            "note": note,
        })
        if target:
            mapping["accounts"][r["old_id"]] = {
                "new_id": int(target["id"]), "method": method}

    # ---- partners: name -> email -> vat ------------------------------------
    p_by_name: dict[str, list[dict]] = defaultdict(list)
    p_by_email: dict[str, list[dict]] = defaultdict(list)
    p_by_vat: dict[str, list[dict]] = defaultdict(list)
    for r in new_part:
        p_by_name[norm_name(s(r.get("name")))].append(r)
        if s(r.get("email")):
            p_by_email[s(r.get("email")).lower()].append(r)
        if s(r.get("vat")):
            p_by_vat[s(r.get("vat")).lower()].append(r)

    def pick(cands: list[dict], raw_name: str) -> dict | None:
        if len(cands) == 1:
            return cands[0]
        exact = [c for c in cands if s(c.get("name")).casefold() == raw_name.casefold()]
        return exact[0] if len(exact) == 1 else None

    for r in old_part:
        raw = s(r.get("name"))
        cands = p_by_name.get(norm_name(raw)) or []
        method = "name"
        target = pick(cands, raw)
        if target is None and s(r.get("email")):
            tc = p_by_email.get(s(r.get("email")).lower()) or []
            if len(tc) == 1:
                target, method = tc[0], "email"
        if target is None and s(r.get("vat")):
            tc = p_by_vat.get(s(r.get("vat")).lower()) or []
            if len(tc) == 1:
                target, method = tc[0], "vat"
        status = "MATCHED" if target else (
            "AMBIGUOUS" if len(cands) > 1 else "UNMATCHED")
        rows["Partners"].append({
            "old_id": r.get("old_id"), "old_name": raw,
            "old_email": s(r.get("email")), "old_vat": s(r.get("vat")),
            "old_is_company": b(r.get("is_company")),
            "new_id": target["id"] if target else "",
            "new_name": s(target.get("name")) if target else "",
            "method": method if target else "",
            "status": status,
            "candidates": "; ".join(
                f"{c['id']}:{s(c.get('name'))}" for c in cands[:4]) if len(cands) > 1 else "",
        })
        if target:
            mapping["partners"][r["old_id"]] = {
                "new_id": int(target["id"]), "method": method}

    # ---- currencies / countries: simple key matches ------------------------
    rows["Currencies"] = []
    cur_by_name = {s(r.get("name")).upper(): r for r in load(NEW / "currencies.csv")}
    for r in load(OLD / "currencies.csv"):
        t = cur_by_name.get(s(r.get("name")).upper())
        rows["Currencies"].append({
            "old_id": r.get("old_id"), "old_name": s(r.get("name")),
            "new_id": t["id"] if t else "", "new_name": s(t.get("name")) if t else "",
            "method": "name" if t else "", "status": "MATCHED" if t else "UNMATCHED"})
        if t:
            mapping.setdefault("currencies", {})[r["old_id"]] = {
                "new_id": int(t["id"]), "method": "name"}

    rows["Countries"] = []
    ctry_by_code = {s(r.get("code")).upper(): r for r in load(NEW / "countries.csv")}
    for r in load(OLD / "countries.csv"):
        t = ctry_by_code.get(s(r.get("code")).upper())
        rows["Countries"].append({
            "old_id": r.get("old_id"), "old_code": s(r.get("code")),
            "old_name": s(r.get("name")),
            "new_id": t["id"] if t else "", "method": "code" if t else "",
            "status": "MATCHED" if t else "UNMATCHED"})
        if t:
            mapping.setdefault("countries", {})[r["old_id"]] = {
                "new_id": int(t["id"]), "method": "code"}

    # ---- taxes: exact (name+amount+type), then the emirate-code renames ----
    # The target renamed the 5% emirate taxes (DB->DU, AD->AZ, S->SH, A->AJ,
    # UAQ->UQ, RAK->RK, F->FU).  Flagged for confirmation in the report.
    _EMIRATE = {"DB": "DU", "AD": "AZ", "S": "SH", "A": "AJ",
                "UAQ": "UQ", "RAK": "RK", "F": "FU"}
    new_taxes = load(NEW / "taxes.csv")
    tax_exact: dict[tuple, dict] = {}
    tax_emir: dict[tuple, dict] = {}
    for r in new_taxes:
        key = (norm_name(s(r.get("name"))), round(float(s(r.get("amount")) or -1), 2),
               s(r.get("type_tax_use")))
        tax_exact.setdefault(key, r)
        parts = s(r.get("name")).split()
        if len(parts) == 2 and parts[0] == "5%" and parts[1] in _EMIRATE.values():
            tax_emir[(parts[1], s(r.get("type_tax_use")))] = r
    rows["Taxes"] = []
    for r in load(OLD / "taxes.csv"):
        name = s(r.get("name"))
        amt = round(float(s(r.get("amount")) or -1), 2)
        use = s(r.get("type_tax_use"))
        t, method = tax_exact.get((norm_name(name), amt, use)), "name+amount+type"
        if not t:
            parts = name.split()
            if len(parts) == 2 and parts[0] == "5%" and parts[1] in _EMIRATE:
                t = tax_emir.get((_EMIRATE[parts[1]], use))
                method = "emirate-code (confirm table)"
        suspects = [f"{s(c.get('name'))}={s(c.get('amount'))}% {s(c.get('type_tax_use'))}"
                    for c in new_taxes
                    if s(c.get("type_tax_use")) == use
                    and abs(float(s(c.get("amount")) or -1) - amt) < 0.01][:4]
        rows["Taxes"].append({
            "old_id": r.get("old_id"), "old_name": name, "old_amount": amt,
            "old_type": use,
            "new_id": t["id"] if t else "", "new_name": s(t.get("name")) if t else "",
            "method": method if t else "",
            "status": "MATCHED" if t else "REVIEW",
            "candidates": "" if t else "; ".join(suspects)})
        if t:
            mapping.setdefault("taxes", {})[r["old_id"]] = {
                "new_id": int(t["id"]), "method": method}

    # ---- payment terms / products / users: name-keyed ----------------------
    rows["Payment_Terms"] = []
    pt_by_name = {norm_name(s(r.get("name"))): r for r in load(NEW / "payment_terms.csv")}
    for r in load(OLD / "payment_terms.csv"):
        t = pt_by_name.get(norm_name(s(r.get("name"))))
        rows["Payment_Terms"].append({
            "old_id": r.get("old_id"), "old_name": s(r.get("name")),
            "new_id": t["id"] if t else "", "new_name": s(t.get("name")) if t else "",
            "method": "name" if t else "", "status": "MATCHED" if t else "UNMATCHED"})
        if t:
            mapping.setdefault("payment_terms", {})[r["old_id"]] = {
                "new_id": int(t["id"]), "method": "name"}

    rows["Products"] = []
    new_prod = load(NEW / "products.csv")
    prod_by_code = {s(r.get("default_code")).upper(): r for r in new_prod
                    if s(r.get("default_code"))}
    prod_by_name = {norm_name(s(r.get("name"))): r for r in new_prod}
    for r in load(OLD / "products.csv"):
        t = prod_by_code.get(s(r.get("default_code")).upper()) if s(r.get("default_code")) else None
        method = "default_code"
        if not t:
            t, method = prod_by_name.get(norm_name(s(r.get("name")))), "name"
        if not t:
            method = ""
        rows["Products"].append({
            "old_id": r.get("old_id"), "old_name": s(r.get("name")),
            "old_code": s(r.get("default_code")), "old_type": s(r.get("type")),
            "new_id": t["id"] if t else "", "new_name": s(t.get("name")) if t else "",
            "method": method, "status": "MATCHED" if t else "UNMATCHED"})
        if t:
            mapping.setdefault("products", {})[r["old_id"]] = {
                "new_id": int(t["id"]), "method": method}

    rows["Users"] = []
    new_users = load(NEW / "users.csv")
    u_by_login = {s(r.get("login")).lower(): r for r in new_users}
    u_by_name = {norm_name(s(r.get("name"))): r for r in new_users}
    for r in load(OLD / "users.csv"):
        t = u_by_login.get(s(r.get("login")).lower())
        method = "login"
        if not t:
            t, method = u_by_name.get(norm_name(s(r.get("name")))), "name"
        if not t:
            method = ""
        rows["Users"].append({
            "old_id": r.get("old_id"), "old_login": s(r.get("login")),
            "old_name": s(r.get("name")),
            "new_id": t["id"] if t else "", "new_name": s(t.get("name")) if t else "",
            "method": method, "status": "MATCHED" if t else "UNMATCHED"})
        if t:
            mapping.setdefault("users", {})[r["old_id"]] = {
                "new_id": int(t["id"]), "method": method}

    # ---- fiscal positions: name (+ Non-UAE alias) ---------------------------
    rows["Fiscal_Positions"] = []
    fp_by_name = {norm_name(s(r.get("name"))): r for r in load(NEW / "fiscal_positions.csv")}
    fp_by_name.setdefault(norm_name("Non UAE"),
                          fp_by_name.get(norm_name("Non-United Arab Emirates")))
    for r in load(OLD / "fiscal_positions.csv"):
        t = fp_by_name.get(norm_name(s(r.get("name"))))
        method = "name" if t else ""
        if not t and norm_name(s(r.get("name"))) == norm_name("Non-UAE"):
            t = fp_by_name.get(norm_name("Non UAE"))
            method = "name-alias (Non-UAE -> Non-United Arab Emirates)"
        rows["Fiscal_Positions"].append({
            "old_id": r.get("old_id"), "old_company": s(r.get("company_id")),
            "old_name": s(r.get("name")),
            "new_id": t["id"] if t else "", "new_name": s(t.get("name")) if t else "",
            "method": method, "status": "MATCHED" if t else "UNMATCHED"})
        if t:
            mapping.setdefault("fiscal_positions", {})[r["old_id"]] = {
                "new_id": int(t["id"]), "method": method}

    # ---- payment methods: from the (name, payment_type) pairs actually used -
    rows["Payment_Methods"] = []
    pm_target = {(norm_name(s(r.get("name"))), s(r.get("payment_type"))): r
                 for r in load(NEW / "payment_methods.csv")}
    seen_methods: set[tuple] = set()
    for r in load(OLD / "payments.csv"):
        m = s(r.get("payment_method_id"))
        if not m:
            continue
        mname = m.rsplit(" (", 1)[0]
        ptype = s(r.get("payment_type"))
        if (mname, ptype) in seen_methods:
            continue
        seen_methods.add((mname, ptype))
        t = pm_target.get((norm_name(mname), ptype))
        rows["Payment_Methods"].append({
            "old_ref": m, "old_payment_type": ptype,
            "new_id": t["id"] if t else "", "new_name": s(t.get("name")) if t else "",
            "new_type": s(t.get("payment_type")) if t else "",
            "method": "name+type" if t else "",
            "status": "MATCHED" if t else "UNMATCHED"})
        if t:
            mapping.setdefault("payment_methods", {})[m] = {
                "new_id": int(t["id"]), "method": "name+type"}

    # ---- summary -----------------------------------------------------------
    covered_new_partner = {m["new_id"] for m in mapping["partners"].values()}
    target_only = [{"id": r["id"], "name": s(r.get("name")),
                    "email": s(r.get("email")), "is_company": b(r.get("is_company"))}
                   for r in new_part if int(r["id"]) not in covered_new_partner]
    summary: list[dict] = []
    for key, sheet in (("companies", "Companies"), ("journals", "Journals"),
                       ("accounts", "Accounts"), ("partners", "Partners"),
                       ("currencies", "Currencies"), ("countries", "Countries"),
                       ("taxes", "Taxes"), ("payment_terms", "Payment_Terms"),
                       ("products", "Products"), ("users", "Users"),
                       ("fiscal_positions", "Fiscal_Positions"),
                       ("payment_methods", "Payment_Methods")):
        rs = rows[sheet]
        methods = defaultdict(int)
        for r in rs:
            methods[r.get("method") or "-"] += 1
        matched = sum(1 for r in rs if r.get("status", "MATCHED") == "MATCHED")
        row = {
            "entity": sheet,
            "old_records": len(rs),
            "target_records": {
                "Companies": len(new_comp), "Journals": len(new_jour),
                "Accounts": len(new_acc), "Partners": len(new_part)}.get(sheet, ""),
            "matched": matched,
            "ambiguous": sum(1 for r in rs if r.get("status") == "AMBIGUOUS"),
            "review": sum(1 for r in rs if r.get("status") == "REVIEW"),
            "unmatched": sum(1 for r in rs if r.get("status") == "UNMATCHED"),
            "coverage_pct": round(100 * matched / max(1, len(rs)), 1),
            "methods": ", ".join(f"{k}={v}" for k, v in sorted(methods.items())),
        }
        if sheet == "Partners":
            row["target_referenced"] = f"{len(covered_new_partner)}/{len(new_part)}"
        summary.append(row)

    wb = Workbook()
    wb.remove(wb.active)
    _add_sheet(wb, "Summary", summary)
    _add_sheet(wb, "Companies", rows["Companies"])
    _add_sheet(wb, "Journals", rows["Journals"])
    _add_sheet(wb, "Accounts", rows["Accounts"])
    _add_sheet(wb, "Partners", rows["Partners"])
    _add_sheet(wb, "Currencies", rows["Currencies"])
    _add_sheet(wb, "Countries", rows["Countries"])
    _add_sheet(wb, "Taxes", rows["Taxes"])
    _add_sheet(wb, "Payment_Terms", rows["Payment_Terms"])
    _add_sheet(wb, "Products", rows["Products"])
    _add_sheet(wb, "Users", rows["Users"])
    _add_sheet(wb, "Fiscal_Positions", rows["Fiscal_Positions"])
    _add_sheet(wb, "Payment_Methods", rows["Payment_Methods"])
    _add_sheet(wb, "Target_Only_Partners", target_only)
    wb.save(OUT_XLSX)
    OUT_JSON.write_text(json.dumps(mapping, indent=1), encoding="utf-8")

    for r in summary:
        print(f"  {r['entity']:<10} {r['matched']:>5}/{r['old_records']:<5} matched "
              f"({r['coverage_pct']:>5}%)  ambiguous={r['ambiguous']:<4} "
              f"unmatched={r['unmatched']:<4}  [{r['methods']}]")
    print(f"-> {OUT_XLSX.name}, {OUT_JSON.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
