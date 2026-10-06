"""Probe the join keys between the spreadsheets and Odoo.

The workbooks key on (Project Name, Unit No, Client Name). Before writing a
reconciler we must confirm those concepts actually exist in Odoo and how:

* units / properties  -> product.product? which fields carry unit + project?
* invoices            -> account.move.real_estate_ref links an invoice to a unit?
* payments            -> account.payment.real_estate_ref?
* customers           -> res.partner normalisation quality

Run: python probe_join_keys.py
"""

from __future__ import annotations

from __future__ import annotations as _a  # noqa: F401

import sys

from pgre_client import OdooClient, OdooError


def main() -> int:
    for _s in ("stdout", "stderr"):
        st = getattr(sys, _s, None)
        if st and hasattr(st, "reconfigure"):
            try:
                st.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass

    c = OdooClient()
    print(f"Connected: {c.db} ({c.about().get('server_version')})\n")

    print("=" * 78)
    print("1. PRODUCT / UNIT identity fields (product.product)")
    print("=" * 78)
    fg = c.fields_get("product.product", attributes=["type", "string"])
    for f in ("name", "default_code", "building_name", "building_name_ar",
              "floor", "bedrooms", "property_area", "city", "master_community",
              "unit_type", "no_of_parking", "property_type_id", "property_category_id",
              "project_id", "project_type", "is_property", "net_price", "total_value",
              "lst_price", "list_price"):
        if f in fg:
            print(f"  {f:<26} {fg[f].get('type'):<12} {fg[f].get('string')}")
    print()
    rows = c.search_read("product.product",
                         [("is_property", "=", True)] if "is_property" in fg else [],
                         ["name", "default_code", "building_name", "floor",
                          "property_area", "city", "net_price", "is_property"],
                         limit=12, order="id asc")
    print(f"  sample properties (is_property=True): {len(rows)}")
    for r in rows:
        print(f"    name={str(r.get('name'))[:34]:<36} code={str(r.get('default_code'))[:14]:<16}"
              f"bldg={str(r.get('building_name'))[:14]:<16} floor={str(r.get('floor')):<6}"
              f"area={str(r.get('property_area')):<10} city={str(r.get('city'))[:14]}")
    tot_props = c.search_count("product.product", [("is_property", "=", True)]) if "is_property" in fg else 0
    print(f"  TOTAL properties: {tot_props}")
    print(f"  TOTAL products  : {c.search_count('product.product', [])}")

    print()
    print("=" * 78)
    print("2. account.move.real_estate_ref  (invoice -> unit link)")
    print("=" * 78)
    if "real_estate_ref" in c.fields_get("account.move", attributes=["type"]):
        n_with = c.search_count("account.move", [("real_estate_ref", "!=", False)])
        n_inv = c.search_count("account.move", [("move_type", "=", "out_invoice"),
                                                ("real_estate_ref", "!=", False)])
        print(f"  moves with real_estate_ref : {n_with:,}")
        print(f"  customer invoices with ref  : {n_inv:,}")
        rows = c.search_read("account.move",
                             [("real_estate_ref", "!=", False), ("move_type", "=", "out_invoice")],
                             ["name", "real_estate_ref", "partner_id", "invoice_date",
                              "amount_total", "property_id", "payment_state"],
                             limit=12, order="id asc")
        for r in rows:
            print(f"    {str(r.get('name')):<20} ref={str(r.get('real_estate_ref'))[:24]:<26}"
                  f"partner={str((r.get('partner_id') or ['',''])[1])[:22]:<24}"
                  f"{str(r.get('invoice_date')):<12}{r.get('amount_total')!s:>14}")
    else:
        print("  real_estate_ref not present on account.move")

    print()
    print("=" * 78)
    print("3. account.payment.real_estate_ref")
    print("=" * 78)
    if "real_estate_ref" in c.fields_get("account.payment", attributes=["type"]):
        n = c.search_count("account.payment", [("real_estate_ref", "!=", False)])
        print(f"  payments with real_estate_ref: {n:,}")
        rows = c.search_read("account.payment", [("real_estate_ref", "!=", False)],
                             ["name", "real_estate_ref", "partner_id", "date",
                              "amount", "payment_type"], limit=10, order="id asc")
        for r in rows:
            print(f"    {str(r.get('name')):<18} ref={str(r.get('real_estate_ref'))[:24]:<26}"
                  f"{str(r.get('date')):<12}{r.get('amount')!s:>14} {r.get('payment_type')}")

    print()
    print("=" * 78)
    print("4. Projects / buildings vocabulary from Odoo")
    print("=" * 78)
    for field in ("building_name", "city", "master_community", "project_id"):
        if field not in fg:
            continue
        try:
            groups = c.execute_kw("product.product", "read_group", [], {
                "domain": [], "fields": [field], "groupby": [field],
                "lazy": True, "limit": 20}) or []
        except OdooError as exc:
            print(f"  {field}: ERR {exc}")
            continue
        vals = [str(g.get(field)) for g in groups[:15]]
        print(f"  {field}: {vals}")

    print()
    print("=" * 78)
    print("5. Partner name matchability (fuzzy feasibility)")
    print("=" * 78)
    partners = c.search_read("res.partner",
                             [("customer_rank", ">", 0)],
                             ["name", "email", "phone", "vat"],
                             limit=8, order="customer_rank desc")
    for p in partners:
        print(f"    {str(p.get('name'))[:40]:<42} {str(p.get('email'))[:28]:<30}"
              f"{str(p.get('phone'))[:16]:<18} vat={str(p.get('vat'))[:16]}")
    print(f"  customers total: {c.search_count('res.partner', [('customer_rank','>',0)])}")

    print()
    print("=" * 78)
    print("6. sale.order presence (order -> invoice -> payment chain)")
    print("=" * 78)
    for m in ("sale.order", "sale.order.line"):
        try:
            print(f"  {m}: {c.search_count(m, []):,} records")
        except OdooError as exc:
            print(f"  {m}: unavailable ({str(exc)[:60]})")
    if True:
        try:
            so = c.search_read("sale.order",
                               [("state", "in", ["sale", "done", "invoiced"])],
                               ["name", "partner_id", "date_order", "amount_total",
                                "state", "invoice_ids"], limit=8, order="id desc")
            print("  sample sale orders:")
            for s in so:
                inv = s.get("invoice_ids") or []
                print(f"    {str(s.get('name')):<18}{str(s.get('state')):<10}"
                      f"{str(s.get('date_order'))[:10]:<12}{s.get('amount_total')!s:>14} "
                      f"invoices={len(inv)} partner={str((s.get('partner_id') or ['',''])[1])[:24]}")
        except OdooError as exc:
            print(f"  sale orders: ERR {str(exc)[:80]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())