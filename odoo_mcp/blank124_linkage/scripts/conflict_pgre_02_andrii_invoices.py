import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

print("=== pgre: unit 608 / 606 templates (community) ===")
for no in ("608", "606"):
    for p in c.search_read("product.template", [("name", "=", no)], fields=["name", "master_community", "unit_type"], limit=10):
        print("  ", p)

print("\n=== pgre: Andrii Levreshov payments (all) ===")
for r in c.search_read("account.payment", [("partner_id.name", "ilike", "Levres")],
                        fields=["name", "partner_id", "amount", "date", "property_id"], limit=40):
    print(f"   {r['date']} {r['amount']:>12} {r['name']:<20} prop={r.get('property_id')}")

print("\n=== pgre: Andrii invoices 2024 (property + contract ref) ===")
for m in c.search_read("account.move", [("partner_id.name", "ilike", "Levres"), ("move_type", "=", "out_invoice"), ("date", ">=", "2024-01-01"), ("date", "<=", "2024-12-31")],
                       fields=["name", "amount_total", "date", "property_id", "ref"], limit=30):
    print(f"   {m['date']} {m['amount_total']:>12} {m['name']:<22} prop={m.get('property_id')} ref={m.get('ref')}")

print("\n=== pgre: Plamen Petrov invoices (property + contract ref) ===")
for m in c.search_read("account.move", [("partner_id.name", "ilike", "Petrov"), ("move_type", "=", "out_invoice")],
                       fields=["name", "amount_total", "date", "property_id", "ref"], limit=25):
    print(f"   {m['date']} {m['amount_total']:>12} {m['name']:<22} prop={m.get('property_id')} ref={m.get('ref')}")

print("\n=== pgre: Halil Erseven invoices 2026-07 (property + contract ref) ===")
for m in c.search_read("account.move", [("partner_id.name", "ilike", "Erseven"), ("move_type", "=", "out_invoice"), ("date", ">=", "2026-06-01"), ("date", "<=", "2026-09-30")],
                       fields=["name", "amount_total", "date", "property_id", "ref"], limit=25):
    print(f"   {m['date']} {m['amount_total']:>12} {m['name']:<22} prop={m.get('property_id')} ref={m.get('ref')}")
