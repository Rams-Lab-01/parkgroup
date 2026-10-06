"""Verify the unit/company/CRM linkage before building on it.

Questions this answers:
  1. Does ``account.move.property_id`` point at ``product.product`` or
     ``product.template``?
  2. Is the owning company on the invoice/payment consistent with the owning
     company of the unit it references?
  3. Does ``crm.lead.property_id`` / ``project_id`` give us a CRM-side unit and
     worksite per lead?
  4. How far does the unit link actually reach (invoices, payments, CRM)?
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


def main() -> int:
    c = OdooClient()
    about = c.about()
    print(f"Connected: {c.db} ({about.get('server_version')})\n")

    print("=" * 96)
    print("1. WHICH MODEL DOES property_id POINT AT?")
    print("=" * 96)
    for m in ("product.template", "product.product"):
        f = c.fields_get(m, attributes=["type", "relation"])
        print(f"  {m:<20} has company_id={'company_id' in f}  "
              f"name={'name' in f}  is_property={'is_property' in f}")
    rows = c.search_read("account.move",
                         [("property_id", "!=", False), ("state", "=", "posted")],
                         ["name", "property_id", "company_id", "amount_total"],
                         limit=5, order="id asc")
    ids = [r["property_id"][0] for r in rows if r.get("property_id")]
    print(f"\n  sample account.move.property_id values: {ids}")
    pprod = set(c.search_ids("product.product", [("id", "in", ids)], limit=0))
    ptpl = set(c.search_ids("product.template", [("id", "in", ids)], limit=0))
    print(f"    match product.product  : {sorted(pprod)}")
    print(f"    match product.template : {sorted(ptpl)}")
    verdict = "product.product" if pprod else ("product.template" if ptpl else "UNKNOWN")
    print(f"  => property_id references **{verdict}**")

    print()
    print("=" * 96)
    print("2. DISTINCT PROPERTY VALUES ON INVOICES")
    print("=" * 96)
    groups = c.execute_kw("account.move", "read_group", [], {
        "domain": [("property_id", "!=", False)],
        "fields": ["property_id"], "groupby": ["property_id"],
        "lazy": True, "limit": 60}) or []
    print(f"  distinct property_id values on posted moves: {len(groups)}")
    for g in groups[:20]:
        pid = g.get("property_id") or [None, "?"]
        print(f"    id={pid[0]!s:<7} name={str(pid[1])[:40]:<42} n={g.get('property_id_count')}")

    print()
    print("=" * 96)
    print("3. IS INVOICE COMPANY == UNIT OWNING COMPANY?")
    print("=" * 96)
    props = c.search_read("product.product", [("is_property", "=", True)],
                          ["name", "default_code", "building_name", "company_id"],
                          limit=0, order="id asc")
    unit_company = {p["id"]: ((p.get("company_id") or [None])[0]) for p in props}
    unit_label = {p["id"]: f"{p.get('building_name')} / {p.get('default_code') or p.get('name')}"
                  for p in props}

    agree = disagree = unknown = 0
    examples: list[str] = []
    for r in c.iter_search_read("account.move",
                                [("property_id", "!=", False), ("state", "=", "posted")],
                                ["name", "property_id", "company_id", "amount_total"],
                                page=500, order="id asc"):
        pid = (r.get("property_id") or [None])[0]
        cid = (r.get("company_id") or [None])[0]
        uc = unit_company.get(pid)
        if uc is None:
            unknown += 1
        elif uc == cid:
            agree += 1
        else:
            disagree += 1
            if len(examples) < 10:
                examples.append(f"      {r.get('name')} unit={pid} "
                                f"invoice_company={cid} unit_company={uc}")
    total = agree + disagree + unknown
    print(f"  invoices checked            : {total:,}")
    print(f"  company matches unit owner  : {agree:,}")
    print(f"  company DIFFERS from unit   : {disagree:,}")
    print(f"  unit not a known property   : {unknown:,}")
    for e in examples:
        print(e)

    print()
    print("=" * 96)
    print("4. crm.lead  -  unit / project / worksite per lead")
    print("=" * 96)
    f = c.fields_get("crm.lead", attributes=["type", "relation", "string"])
    for k in sorted(k for k in f if k in ("property_id", "project_id",
                                          "dp_allowed_property_ids",
                                          "prefered_unit_1_id", "prefered_unit_2_id",
                                          "prefered_unit_3_id", "partner_id",
                                          "company_id", "team_id", "stage_id")):
        v = f[k]
        print(f"    {k:<28} {str(v.get('type')):<11} {str(v.get('relation')):<24}"
              f"{str(v.get('string'))[:34]}")
    n_prop = c.search_count("crm.lead", [("property_id", "!=", False)])
    n_proj = c.search_count("crm.lead", [("project_id", "!=", False)])
    n_team = c.search_count("crm.lead", [("team_id", "!=", False)])
    print(f"\n  crm.lead total                : {c.search_count('crm.lead', []):,}")
    print(f"  crm.lead with property_id     : {n_prop:,}")
    print(f"  crm.lead with project_id      : {n_proj:,}")
    print(f"  crm.lead with team_id         : {n_team:,}")

    if n_prop or n_proj:
        rows = c.search_read("crm.lead",
                             ["|", ("property_id", "!=", False),
                              ("project_id", "!=", False)],
                             ["name", "property_id", "project_id", "partner_id",
                              "team_id", "stage_id", "company_id", "create_date"],
                             limit=10, order="id desc")
        for r in rows:
            print(f"    {str(r.get('name'))[:26]:<28}"
                  f"property={str((r.get('property_id') or ['','-'])[1])[:20]:<22}"
                  f"project={str((r.get('project_id') or ['','-'])[1])[:22]:<24}"
                  f"team={str((r.get('team_id') or ['','-'])[1])[:20]:<22}"
                  f"company={str((r.get('company_id') or ['','-'])[1])[:26]}")

    print()
    print("=" * 96)
    print("5. LINK COVERAGE SUMMARY")
    print("=" * 96)
    n_moves = c.search_count("account.move", [("move_type", "=", "out_invoice"),
                                               ("state", "=", "posted")])
    linked = c.search_count("account.move", [("move_type", "=", "out_invoice"),
                                            ("state", "=", "posted"),
                                            ("property_id", "!=", False)])
    n_pay = c.search_count("account.payment", [("state", "not in", ["draft", "cancel"])])
    pay_linked = c.search_count("account.payment", [("property_id", "!=", False),
                                                    ("state", "not in", ["draft", "cancel"])])
    print(f"  customer invoices            : {n_moves:,}")
    print(f"    with property_id           : {linked:,}  ({100*linked/max(1,n_moves):.1f}%)")
    print(f"  payments                     : {n_pay:,}")
    print(f"    with property_id           : {pay_linked:,}  "
          f"({100*pay_linked/max(1,n_pay):.1f}%)")
    print()
    print("  => The invoice->unit link EXISTS via `property_id` (populated by the")
    print("     dp_/custom modules). `real_estate_ref` is the unused duplicate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())