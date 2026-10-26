"""Unit-attribution plan: prod vs the PGRE pre-migration export (final).

Matching
  invoice : (partner, name, amount)   - invoice names survived the migration
  payment : (partner, amount, date)   - receipt names were renumbered; the memo
            ("Payment for EOI of lead: 520") disambiguates
Unit of truth: the unit PGRE itself recorded on the row.  The old template id is
mapped to the prod unit through the migration's own mapping
(target_mapping_2026-10-06.json), falling back to company+unit number for the
old templates that mapping did not carry.
"""
import csv
import io
import json
import re
from collections import Counter, defaultdict

ROOT = r"C:\Parkgroup Data\odoo_mcp"
OUT = r"C:\Users\USER\AppData\Local\Temp\pg"

# PGRE legal entity -> prod project code (business rule used by the migration)
COMPANY_PROJECT = {
    "PARK REAL ESTATE DEVELOPMENT LLC OPC": "BR1",
    "PBR REAL ESTATE DEVELOPMENT LLC OPC": "BR2",
    "PARK RESIDENCY REAL ESTATE DEVELOPMENT LLC": "RES",
    "AIWA REAL ESTATE DEVELOPMENT LLC": "GOLF",
}


def norm(s):
    s = re.sub(r"\s*\(\d+\)$", "", (s or "").strip())
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def ref_parts(value):
    """'[412] 412 (2889)' -> ('[412] 412', 2889)"""
    if not value or value in ("False", "None", ""):
        return None
    m = re.match(r"^(.*?)\s*\((\d+)\)\s*$", str(value).strip())
    return (m.group(1), int(m.group(2))) if m else None


def unit_no(disp):
    m = re.match(r"^\[([^\]]+)\]", disp or "") or re.match(r"^(\d+)", disp or "")
    return m.group(1) if m else ""


def memo_unit(memo):
    m = re.search(r"(?:unit|lead)\s*:?\s*(\d+)\s*$", (memo or "").strip(), re.I)
    return m.group(1) if m else None


mapping = json.load(open(f"{ROOT}/target_mapping_2026-10-06.json", encoding="utf-8"))
old_to_new = {k: v["new_id"] for k, v in mapping["units"].items()}

prod_units = list(csv.DictReader(io.open(f"{OUT}/prod_units2.csv", encoding="utf-8-sig")))
prod_by_key = {}
prod_name = {}
for r in prod_units:
    prod_by_key[(r["project_code"], (r["unit_number"] or "").strip())] = r["id"]
    prod_name[r["id"]] = r["name"]

prod_pay = list(csv.DictReader(io.open(f"{OUT}/prod_payments.csv", encoding="utf-8-sig")))
prod_inv = list(csv.DictReader(io.open(f"{OUT}/prod_invoices.csv", encoding="utf-8-sig")))
pg_pay = list(csv.DictReader(io.open(f"{ROOT}/migration_out/payments.csv", encoding="utf-8-sig")))
pg_inv = list(csv.DictReader(io.open(f"{ROOT}/migration_out/invoices.csv", encoding="utf-8-sig")))


def pgre_unit_row(row):
    """The prod unit id PGRE's own reference points at, or None."""
    parts = ref_parts(row.get("property_id"))
    if not parts:
        return None, ""
    disp, old_id = parts
    if str(old_id) in old_to_new:
        return old_to_new[str(old_id)], unit_no(disp)
    company = (ref_parts(row.get("company_id")) or ("", 0))[0]
    code = COMPANY_PROJECT.get(company, "")
    tgt = prod_by_key.get((code, unit_no(disp)))
    return (tgt if tgt else None), unit_no(disp)


pay_by_key, pay_by_memo = defaultdict(list), defaultdict(list)
for r in pg_pay:
    k = (norm(r.get("partner_id")), round(float(r.get("amount") or 0), 2), (r.get("date") or "")[:10])
    pay_by_key[k].append(r)
    mu = memo_unit(r.get("memo"))
    if mu:
        pay_by_memo[(norm(r.get("partner_id")), round(float(r.get("amount") or 0), 2), mu)].append(r)

inv_by_key, inv_by_date = defaultdict(list), defaultdict(list)
for r in pg_inv:
    inv_by_key[(norm(r.get("partner_id")), re.sub(r"\s*\[[A-Z]+\]$", "", (r.get("name") or "").strip()),
                round(float(r.get("amount_total") or 0), 2))].append(r)
    inv_by_date[(norm(r.get("partner_id")), round(float(r.get("amount_total") or 0), 2),
                 (r.get("invoice_date") or "")[:10])].append(r)


def pick(cands, want_unit=None):
    """Return (pgre row, how)."""
    if not cands:
        return None, "no-match"
    if len(cands) == 1:
        return cands[0], "unique"
    if want_unit is not None:
        for c in cands:
            u, no = pgre_unit_row(c)
            if no == str(want_unit):
                return c, "unique-unit"
    units_found = {pgre_unit_row(c)[0] for c in cands}
    if len(units_found) == 1:
        return cands[0], "all-same"
    return None, "ambiguous"


rows = []
for r in prod_pay:
    prod_unit = r["property_id"] or r["manual_property_id"] or ""
    if not prod_unit:
        continue
    m = re.search(r"(\d+)\s*$", prod_name.get(prod_unit, ""))
    want = m.group(1) if m else None
    memo_u = memo_unit(r.get("memo"))
    key = (norm(r.get("partner")), round(float(r["amount"]), 2), (r["date"] or "")[:10])
    cands = pay_by_memo.get((key[0], key[1], memo_u), []) if memo_u else []
    how = "memo"
    if not cands:
        cands, how = pay_by_key.get(key, []), "date"
    cand, res = pick(cands, want)
    new, pno = (None, "")
    if cand is not None:
        new, pno = pgre_unit_row(cand)
    if res in ("no-match", "ambiguous"):
        action = "review"
    elif new is None:
        action = "clear-unit"
    elif str(new) != str(prod_unit):
        action = "repoint"
    else:
        action = "keep"
    rows.append(dict(kind="payment", id=r["id"], name=r["name"], amount=r["amount"], date=r["date"],
                     partner=r["partner"], prod_unit=prod_unit, prod_unit_name=prod_name.get(prod_unit, ""),
                     memo_unit=memo_u or "", pgre_unit=pno or "", pgre_prod_unit=new or "",
                     how=how + "/" + res, action=action))

for r in prod_inv:
    prod_unit = r["property_id"] or ""
    m = re.search(r"(\d+)\s*$", prod_name.get(prod_unit, ""))
    want = m.group(1) if m else None
    key = (norm(r.get("partner")), re.sub(r"\s*\[[A-Z]+\]$", "", (r["name"] or "").strip()),
           round(float(r["amount_total"]), 2))
    cands, how = inv_by_key.get(key, []), "name"
    if not cands:
        key2 = (norm(r.get("partner")), round(float(r["amount_total"]), 2), (r.get("invoice_date") or "")[:10])
        cands, how = inv_by_date.get(key2, []), "date"
    cand, res = pick(cands, want)
    new, pno = (None, "")
    if cand is not None:
        new, pno = pgre_unit_row(cand)
    if res in ("no-match", "ambiguous"):
        action = "review"
    elif new is None:
        action = "clear-unit"
    elif str(new) != str(prod_unit):
        action = "repoint"
    else:
        action = "keep"
    rows.append(dict(kind="invoice", id=r["id"], name=r["name"], amount=r["amount_total"], date=r["invoice_date"],
                     partner=r["partner"], prod_unit=prod_unit, prod_unit_name=prod_name.get(prod_unit, ""),
                     memo_unit="", pgre_unit=pno or "", pgre_prod_unit=new or "", how=how + "/" + res, action=action))

with io.open(f"{OUT}/unit_attribution_plan.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print("rows:", len(rows))
print(Counter((r["kind"], r["action"]) for r in rows))
for kind in ("payment", "invoice"):
    sel = [r for r in rows if r["kind"] == kind and r["action"] != "keep"]
    money = round(sum(float(r["amount"]) for r in sel), 2)
    print(f"\n=== {kind}: {len(sel)} to fix, {money:,.2f}")
    byp = Counter(r["partner"] for r in sel)
    print("   partners:", byp.most_common(6))
    for r in sel:
        print(f'  {r["action"]:10} id={r["id"]:>6} {r["name"][:22]:22} {r["amount"]:>12} {r["partner"][:22]:22} '
              f'prod={r["prod_unit"]}({r["prod_unit_name"][-11:]}) pgre={r["pgre_unit"] or "-"}->{r["pgre_prod_unit"] or "-"} [{r["how"]}]')
