import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

print("=== pgre invoices on unit 608 @ PARK BEACH RESIDENCE (2163) ===")
for m in c.search_read("account.move", [("property_id", "=", 2163), ("move_type", "=", "out_invoice")],
                       fields=["name", "amount_total", "date", "ref", "partner_id"], limit=25):
    print(f"   {m['date']} {m['amount_total']:>12} {m['name']:<22} ref={(m.get('ref') or '')[:34]:<34} partner={str((m.get('partner_id') or [None,None])[1])[:38]}")

print("\n=== pgre receipts on unit 608 @ PARK BEACH RESIDENCE (2163) ===")
for p in c.search_read("account.payment", [("property_id", "=", 2163)],
                       fields=["name", "amount", "date", "partner_id", "journal_id"], limit=25):
    print(f"   {p['date']} {p['amount']:>12} {p['name']:<20} partner={str((p.get('partner_id') or [None,None])[1])[:38]}")

print("\n=== pgre: any partner owning those 608 receipts ===")
for p in c.search_read("account.payment", [("property_id", "=", 2163)],
                       fields=["partner_id"], limit=5):
    pid = p["partner_id"][0]
    rec = c.read("res.partner", [pid], ["name", "email", "phone", "parent_id", "active"])[0]
    print("   partner record:", rec)
