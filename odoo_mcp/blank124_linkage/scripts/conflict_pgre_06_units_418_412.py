import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

print("=== pgre: every receipt on unit 418 (2895) ===")
rows = c.search_read("account.payment", [("property_id", "=", 2895)], limit=40)
for p in rows:
    print("   ", p.get("date"), p.get("amount"), p.get("name"), (p.get("partner_id") or [None, None])[1])

print("\n=== pgre: receipts on unit 412 (2889) ===")
for p in c.search_read("account.payment", [("property_id", "=", 2889)], limit=40):
    print("   ", p.get("date"), p.get("amount"), p.get("name"), (p.get("partner_id") or [None, None])[1])

print("\n=== pgre: ptre 2895 vs 2889 communities ===")
for pid in (2889, 2895):
    print("   ", c.read("product.template", [pid], ["name", "master_community", "unit_type"]))
