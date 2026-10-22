import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

print("=== pgre: invoice of 108228.86 (the target's INV/2026/00008 [PRES]) ===")
for m in c.search_read("account.move", [("amount_total", "=", 108228.86), ("move_type", "=", "out_invoice")],
                       fields=["name", "partner_id", "date", "property_id", "ref", "payment_state"], limit=10):
    print("   ", m)

print("\n=== pgre: every 30,000 receipt in 2026 (Jan) ===")
for p in c.search_read("account.payment", [("date", ">=", "2026-01-01"), ("date", "<=", "2026-01-31"), ("amount", "=", 30000.0)],
                       fields=["name", "partner_id", "date", "property_id"], limit=30):
    print("   ", p["date"], p["amount"], p["name"], (p.get("partner_id") or [None, None])[1], p.get("property_id"))

print("\n=== pgre: unit 412 / 418 templates (community) ===")
for no in ("412", "418"):
    for p in c.search_read("product.template", [("name", "=", no)], fields=["name", "master_community", "unit_type"], limit=10):
        print("   ", p)

print("\n=== pgre: receipts on the Park Residency 412 (2889) ===")
for p in c.search_read("account.payment", [("property_id", "=", 2889)],
                       fields=["name", "amount", "date", "partner_id"], limit=20):
    print(f"   {p['date']} {p['amount']:>10} {p['name']:<20} {(p.get('partner_id') or [None,None])[1]}")
