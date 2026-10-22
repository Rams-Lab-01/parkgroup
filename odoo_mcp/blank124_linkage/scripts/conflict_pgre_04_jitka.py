import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

print("=== pgre: Jitka Zieba invoices ===")
for m in c.search_read("account.move", [("partner_id.name", "ilike", "Zieba"), ("move_type", "=", "out_invoice")],
                       fields=["name", "amount_total", "date", "property_id", "ref", "payment_state"], limit=20):
    print(f"   {m['date']} {m['amount_total']:>12} {m['name']:<22} state={m.get('payment_state'):<9} prop={m.get('property_id')} ref={(m.get('ref') or '')[:30]}")

print("\n=== pgre: Jitka Zieba payments ===")
for p in c.search_read("account.payment", [("partner_id.name", "ilike", "Zieba")],
                       fields=["name", "amount", "date", "property_id"], limit=20):
    print(f"   {p['date']} {p['amount']:>12} {p['name']:<20} prop={p.get('property_id')}")

print("\n=== pgre: any payment of 30000 on 2026-01-14 (whoever) ===")
for p in c.search_read("account.payment", [("date", "=", "2026-01-14"), ("amount", "=", 30000.0)],
                       fields=["name", "partner_id", "property_id"], limit=10):
    print("   ", p)
