"""Locate the unit -> owning-company and unit -> CRM links.

The business rule is: a project/unit sits under a specific legal entity
(PARK RESIDENCY is held by PARK RESIDENCY REAL ESTATE DEVELOPMENT LLC). That
attribution has to come from Odoo, not from a name guess.

This probes, in order of directness:
  1. product.product.company_id          - the owning company of each unit
  2. account.move.company_id             - invoicing company per document
  3. account.move/payment.property_id    - property link added by custom modules
  4. CRM models and any custom field that references a unit / project / property
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict

from pgre_client import OdooClient, OdooError

for _s in ("stdout", "stderr"):
    _st = getattr(sys, _s, None)
    if _st and hasattr(_st, "reconfigure"):
        try:
            _st.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass

CRM_CANDIDATES = [
    "crm.lead", "crm.opportunity", "crm.stage", "crm.lead.scoring.frequency",
    "property.property", "property.project",
]
UNIT_HINTS = ("unit", "property", "project", "building", "ref", "size", "bed", "floor")


def main() -> int:
    c = OdooClient()
    print(f"Connected: {c.db} ({c.about().get('server_version')})\n")

    print("=" * 96)
    print("1. COMPANIES")
    print("=" * 96)
    comps = c.read("res.company", c.search_ids("res.company", [], limit=50),
                   ["name", "currency_id", "vat", "parent_id"])
    comp_by_id = {x["id"]: x for x in comps}
    for x in comps:
        print(f"  id={x['id']:<4} {str(x.get('name'))[:58]:<60} "
              f"{(x.get('currency_id') or [None,'?'])[1]}")

    print()
    print("=" * 96)
    print("2. product.product.company_id  - owning company per unit")
    print("=" * 96)
    fg = c.fields_get("product.product", attributes=["type", "string", "relation"])
    if "company_id" in fg:
        print(f"  product.product.company_id exists: {fg['company_id'].get('string')}")
        props = c.search_read("product.product", [("is_property", "=", True)],
                              ["name", "default_code", "building_name", "company_id"],
                              limit=0, order="id asc")
        by_building = defaultdict(Counter)
        unset = Counter()
        for p in props:
            b = str(p.get("building_name") or "(none)")
            cid = p.get("company_id")
            if cid:
                by_building[b][cid[0]] += 1
            else:
                unset[b] += 1
        print()
        for b in sorted(by_building):
            print(f"  {b}")
            for cid, n in by_building[b].most_common():
                nm = (comp_by_id.get(cid) or {}).get("name", f"id {cid}")
                print(f"      {n:>4}  company_id={cid:<4} {nm}")
            if unset.get(b):
                print(f"      {unset[b]:>4}  company_id NOT SET")
        print()
        print(f"  units with company_id set: "
              f"{sum(sum(v.values()) for v in by_building.values())}/{len(props)}")
        print(f"  units with company_id unset: {sum(unset.values())}")
    else:
        print("  product.product.company_id NOT present")

    print()
    print("=" * 96)
    print("3. account.move / account.payment company + property links")
    print("=" * 96)
    for model in ("account.move", "account.payment"):
        fields = c.fields_get(model, attributes=["type", "string", "relation"])
        interesting = [f for f in ("company_id", "property_id", "project_id",
                                   "real_estate_ref", "contract_line_id", "line_id")
                       if f in fields]
        print(f"  {model}: {interesting}")
        if "company_id" in fields and "property_id" in fields:
            n_prop = c.search_count(model, [("property_id", "!=", False)])
            print(f"      records with property_id set: {n_prop:,}")

    print()
    print("=" * 96)
    print("4. CRM MODELS")
    print("=" * 96)
    # Any model whose name mentions crm / lead / opportunity / unit / booking
    for pat in ("crm", "lead", "opportunit", "booking", "reservation", "unit",
                "property", "tenan", "contract"):
        models = c.search_read("ir.model", [("model", "ilike", pat)],
                               ["model", "name"], limit=40)
        interesting = [m for m in models
                       if pat in str(m.get("model")).lower()
                       and not str(m.get("model")).startswith("ir.")]
        for m in interesting:
            print(f"  {str(m.get('model')):<44} {str(m.get('name'))[:44]}")

    print()
    for model in CRM_CANDIDATES:
        try:
            n = c.search_count(model, [])
        except OdooError as exc:
            print(f"  {model:<28} unavailable ({str(exc)[:60]})")
            continue
        if not n:
            print(f"  {model:<28} present but EMPTY")
            continue
        print(f"  {model:<28} {n:,} records")
        f = c.fields_get(model, attributes=["type", "string", "relation"])
        hits = {k: v for k, v in f.items()
                if any(h in k.lower() for h in UNIT_HINTS)}
        for k in sorted(hits)[:24]:
            v = hits[k]
            rel = v.get("relation")
            print(f"        {k:<38} {str(v.get('type')):<11} "
                  f"{str(v.get('string'))[:34]}  -> {rel}")

    print()
    print("=" * 96)
    print("5. DOES ANY LINK AN INVOICE TO A UNIT?")
    print("=" * 96)
    for model, field in (("account.move", "property_id"),
                         ("account.move", "real_estate_ref"),
                         ("account.payment", "property_id"),
                         ("account.payment", "real_estate_ref")):
        try:
            n = c.search_count(model, [(field, "!=", False)])
        except OdooError as exc:
            print(f"  {model}.{field}: {str(exc)[:70]}")
            continue
        status = "POPULATED" if n else "EMPTY"
        print(f"  {model}.{field:<20} {n:>8,}  {status}")
        if n and model == "account.move" and field == "property_id":
            rows = c.search_read(model, [(field, "!=", False)],
                                 ["name", field, "company_id", "partner_id",
                                  "amount_total"], limit=8)
            for r in rows:
                print(f"      {str(r.get('name')):<20} "
                      f"property={str((r.get(field) or ['','?'])[1])[:26]:<28} "
                      f"company={str((r.get('company_id') or ['','?'])[1])[:30]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())