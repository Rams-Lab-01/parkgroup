import os, sys, io, json
from collections import Counter
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

print("=== 1) does unit 309 exist in pgre product.template? ===")
for no in ("309", "307", "310"):
    ps = c.search_read("product.template", [("name", "=", no)], fields=["name", "master_community", "project_id", "unit_type", "product_properties"], limit=20)
    for p in ps:
        print(f"   unit {p['name']:<5} id={p['id']:<6} community={p.get('master_community')} type={p.get('unit_type')} proj={(p.get('project_id') or [None,None])[1]}")

print("\n=== 2) pgre property.contract rows mentioning Fatlawi ===")
for m in ("property.contract", "property.reservation"):
    try:
        n = c.search_count(m, [])
        print(f"   {m}: {n} records total")
    except Exception as e:
        print(f"   {m}: ERR {e}")

# contracts: find by partner name field guesses
for fld in ("partner_id", "client_id", "customer_id", "buyer_id", "investor_id"):
    try:
        rows = c.search_read("property.contract", [(fld, "ilike", "Fatlawi")], fields=["name", fld, "property_id", "product_id", "state", "total_amount"], limit=20)
        if rows:
            print(f"\n   property.contract via {fld}: {len(rows)}")
            for r in rows:
                print("     ", {k: v for k, v in r.items() if k != "id"})
    except Exception as e:
        pass

print("\n=== 3) any CRM lead named 309 / mentioning 309 for Fatlawi ===")
for dom in ([("name", "ilike", "309")], [("name", "ilike", "Fatlawi")], [("property_id.name", "=", "309")]):
    try:
        rows = c.search_read("crm.lead", dom, fields=["name", "partner_id", "property_id", "stage_id", "type", "create_date"], limit=15)
        print(f"   domain {dom}: {len(rows)}")
        for r in rows[:8]:
            print("     ", r.get("name"), "| partner:", (r.get("partner_id") or [None,None])[1], "| prop:", (r.get("property_id") or [None,None])[1], "| stage:", (r.get("stage_id") or [None,None])[1])
    except Exception as e:
        print("   ERR", dom, e)

print("\n=== 4) pgre invoices with the 12 target amounts (any partner) ===")
AMTS = (28000.0, 27970.0, 27470.0, 271419.0, 277418.6)
for a in AMTS:
    for op in ("=", "in"):
        dom = [("amount_total", op, a if op == "=" else [a])]
        try:
            rows = c.search_read("account.move", dom + [("move_type", "=", "out_invoice")], fields=["name", "partner_id", "amount_total", "date", "property_id", "ref"], limit=8)
            if rows:
                print(f"   amount {a}: {len(rows)} invoice(s)")
                for r in rows[:5]:
                    print("     ", r.get("name"), "|", (r.get("partner_id") or [None,None])[1], "|", r.get("date"), "| prop:", r.get("property_id"), "| ref:", (r.get("ref") or "")[:30])
                break
        except Exception as e:
            print("   ERR", a, e)

print("\n=== 5) pgre payments with those amounts (any partner) ===")
for a in AMTS:
    try:
        rows = c.search_read("account.payment", [("amount", "=", a)], fields=["name", "partner_id", "amount", "date", "property_id", "journal_id"], limit=8)
        print(f"   amount {a}: {len(rows)}")
        for r in rows[:5]:
            print("     ", r.get("name"), "|", (r.get("partner_id") or [None,None])[1], "|", r.get("date"), "| prop:", r.get("property_id"))
    except Exception as e:
        print("   ERR", a, e)

print("\n=== 6) pgre leads for any partner whose name contains 'Fatlawi' (wide) ===")
rows = c.search_read("crm.lead", [("name", "ilike", "Fatlawi")], fields=["name", "partner_id", "property_id", "stage_id", "type", "create_date", "description"], limit=20)
print("   leads by name ilike Fatlawi:", len(rows))
for r in rows[:10]:
    print("     ", r.get("name"), "|", (r.get("partner_id") or [None,None])[1], "| prop:", (r.get("property_id") or [None,None])[1], "|", (r.get("description") or "")[:120])
