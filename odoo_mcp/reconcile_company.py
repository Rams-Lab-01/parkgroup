"""Reconcile the company attribution, which the user flagged as the key missing rule.

Business rule (stated by the user):
    a project / unit sits under ONE legal entity, e.g. PARK RESIDENCY is held by
    PARK RESIDENCY REAL ESTATE DEVELOPMENT LLC.

What Odoo actually holds, measured rather than assumed:
  * ``product.product.company_id``  - the owning company of every unit (716/716 set)
  * ``account.move.property_id``    - invoice -> product.**template** (not product)
  * 95.5% of customer invoices and 94.1% of payments have property_id set, so a
    real invoice->unit link DOES exist; ``real_estate_ref`` is a dead duplicate.

The critical trap found here: because ``property_id`` points at
``product.template`` while the unit inventory lives in ``product.product``,
comparing template ids against product ids makes nearly every invoice look like
it points at an unknown unit (416 rows) and makes the invoice company appear to
"disagree" with the unit owner (4,719 rows). Those are artefacts of the wrong
join, not data errors. This script resolves template->product correctly and then
measures genuine company attribution.
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
    print(f"Connected: {c.db} ({c.about().get('server_version')})\n")

    comps = c.read("res.company", c.search_ids("res.company", [], limit=50), ["name"])
    comp_name = {x["id"]: str(x.get("name")) for x in comps}

    # ---- units (product.product)
    units = c.search_read("product.product", [("is_property", "=", True)],
                          ["name", "default_code", "building_name", "company_id",
                           "property_area"], limit=0, order="id asc")
    print("=" * 96)
    print("1. UNIT OWNERSHIP BY COMPANY  (product.product.company_id)")
    print("=" * 96)
    by_building = defaultdict(Counter)
    for u in units:
        cid = (u.get("company_id") or [None])[0]
        by_building[str(u.get("building_name"))][cid] += 1
    for b in sorted(by_building):
        counts = by_building[b]
        owners = {cid: n for cid, n in counts.items()}
        uniq = len(owners)
        flag = "" if uniq == 1 else "  <-- MIXED OWNERSHIP"
        print(f"  {b:<32} {sum(counts.values()):>4} units{flag}")
        for cid, n in sorted(owners.items(), key=lambda kv: -kv[1]):
            print(f"      {n:>4}  {comp_name.get(cid, f'id {cid}')}")

    # ---- template -> product resolution
    print()
    print("=" * 96)
    print("2. RESOLVING account.move.property_id (template) -> unit (product)")
    print("=" * 96)
    tmpl_ids = set(c.search_ids("product.template", [("is_property", "=", True)], limit=0))
    tmpls = c.read("product.template", sorted(tmpl_ids),
                   ["name", "default_code", "building_name", "company_id"])
    print(f"  property templates with is_property: {len(tmpls):,}")
    tmpl_label = {t["id"]: str(t.get("default_code") or t.get("name")) for t in tmpls}
    tmpl_owner = {t["id"]: (t.get("company_id") or [None])[0] for t in tmpls}

    # Build template -> its variant product ids via product_variant_ids.
    t2p: dict[int, list[int]] = {}
    for t in c.iter_search_read("product.template",
                                [("id", "in", sorted(tmpl_ids))],
                                ["product_variant_ids"], page=500, order="id asc"):
        variants = t.get("product_variant_ids") or []
        t2p[t["id"]] = [v[0] for v in variants if isinstance(v, (list, tuple))]

    prod_by_id = {u["id"]: u for u in units}
    print(f"  templates with resolvable variants: {sum(1 for v in t2p.values() if v):,}")

    # A template's owner is what matters; also map unit code -> owner
    code_owner: dict[str, tuple[int, str]] = {}
    for u in units:
        code = str(u.get("default_code") or u.get("name") or "").strip().upper()
        cid = (u.get("company_id") or [None])[0]
        if code:
            code_owner.setdefault(code, (cid, str(u.get("building_name"))))

    print()
    print("=" * 96)
    print("3. INVOICE COMPANY vs UNIT OWNER  (resolved through the template)")
    print("=" * 96)
    agree = disagree = no_unit = no_owner = 0
    pairs: Counter = Counter()
    examples: list[str] = []
    for r in c.iter_search_read("account.move",
                                [("move_type", "in", ["out_invoice", "out_refund"]),
                                 ("state", "=", "posted")],
                                ["name", "property_id", "company_id", "amount_total",
                                 "invoice_date"],
                                page=500, order="id asc"):
        tid = (r.get("property_id") or [None])[0]
        cid = (r.get("company_id") or [None])[0]
        if not tid:
            no_unit += 1
            continue
        owner = tmpl_owner.get(tid)
        if owner is None:
            # fall back to matching by unit code
            code = tmpl_label.get(tid, "").strip().upper()
            owner = code_owner.get(code, (None, None))[0]
        if owner is None:
            no_owner += 1
            continue
        if owner == cid:
            agree += 1
        else:
            disagree += 1
            pairs[(cid, owner)] += 1
            if len(examples) < 8:
                examples.append(
                    f"      {r.get('name'):<18} unit={tmpl_label.get(tid, '?'):<8} "
                    f"invoice_co={comp_name.get(cid, cid)!s:<46} "
                    f"unit_owner={comp_name.get(owner, owner)}")
    total = agree + disagree + no_unit + no_owner
    print(f"  posted customer invoices analysed : {total:,}")
    print(f"  company matches the unit's owner   : {agree:,}  "
          f"({100*agree/max(1,total):.1f}%)")
    print(f"  company DIFFERS from unit owner    : {disagree:,}  "
          f"({100*disagree/max(1,total):.1f}%)")
    print(f"  no property_id on the invoice      : {no_unit:,}")
    print(f"  property_id present, owner unknown : {no_owner:,}")
    print()
    if pairs:
        print("  top (invoice company -> unit owner) mismatches:")
        for (cid, owner), n in pairs.most_common(12):
            print(f"    {n:>5}  invoice={comp_name.get(cid, cid)!s:<46} "
                  f"unit_owner={comp_name.get(owner, owner)}")
    for e in examples:
        print(e)

    # ---- payments
    print()
    print("=" * 96)
    print("4. PAYMENT COMPANY vs UNIT OWNER")
    print("=" * 96)
    agree = disagree = no_unit = 0
    pay_pairs: Counter = Counter()
    for r in c.iter_search_read("account.payment",
                                [("state", "not in", ["draft", "cancel"])],
                                ["name", "property_id", "company_id", "amount",
                                 "payment_type", "partner_type"],
                                page=500, order="id asc"):
        tid = (r.get("property_id") or [None])[0]
        cid = (r.get("company_id") or [None])[0]
        if not tid:
            no_unit += 1
            continue
        owner = tmpl_owner.get(tid)
        if owner is None:
            code = tmpl_label.get(tid, "").strip().upper()
            owner = code_owner.get(code, (None, None))[0]
        if owner is None:
            no_unit += 1
            continue
        if owner == cid:
            agree += 1
        else:
            disagree += 1
            pay_pairs[(cid, owner)] += 1
    print(f"  company matches the unit's owner   : {agree:,}")
    print(f"  company DIFFERS from unit owner    : {disagree:,}")
    print(f"  no resolvable property_id          : {no_unit:,}")
    if pay_pairs:
        print("  top (payment company -> unit owner) mismatches:")
        for (cid, owner), n in pay_pairs.most_common(12):
            print(f"    {n:>5}  payment={comp_name.get(cid, cid)!s:<46} "
                  f"unit_owner={comp_name.get(owner, owner)}")

    # ---- CRM cross-check
    print()
    print("=" * 96)
    print("5. CRM CROSS-CHECK  (crm.lead company vs the project's owner)")
    print("=" * 96)
    bld_owner = {}
    for u in units:
        bld_owner.setdefault(str(u.get("building_name")),
                             (u.get("company_id") or [None])[0])
    rows = c.search_read("crm.lead", [],
                         ["name", "property_id", "project_id", "company_id",
                          "team_id", "partner_id"],
                         limit=0, order="id desc")
    agree = disagree = 0
    crm_pairs: Counter = Counter()
    for r in rows:
        cid = (r.get("company_id") or [None])[0]
        wid = (r.get("project_id") or [None, None])[1]
        if not cid or not wid:
            continue
        owner = bld_owner.get(str(wid))
        if owner is None:
            continue
        if owner == cid:
            agree += 1
        else:
            disagree += 1
            crm_pairs[(str(wid), cid, owner)] += 1
    print(f"  crm.lead with project + company    : {agree + disagree:,}")
    print(f"  company matches project owner      : {agree:,}")
    print(f"  company DIFFERS from project owner : {disagree:,}")
    if crm_pairs:
        print("  mismatches by (worksite, lead company, project owner):")
        for (wid, cid, owner), n in crm_pairs.most_common(12):
            print(f"    {n:>5}  project={wid:<32} "
                  f"lead_co={comp_name.get(cid, cid)!s:<44} "
                  f"owner={comp_name.get(owner, owner)}")

    print()
    print("=" * 96)
    print("6. VERDICT FOR THE RECONCILIATION")
    print("=" * 96)
    print("""  Ground truth for company attribution (use this, do not re-derive):
""")
    for b in sorted(by_building):
        counts = by_building[b]
        for cid, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            print(f"    {b:<32} -> {comp_name.get(cid, cid)}  ({n} units)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())