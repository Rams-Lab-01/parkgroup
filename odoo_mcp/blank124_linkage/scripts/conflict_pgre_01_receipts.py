import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

CASES = [
    ("Andrii Levreshov", "2024-07-01", 616900.0),
    ("Andrii Levreshov", "2024-07-01", 3000.0),
    ("Raphael Phillipe Dominique Francois Emille Goue", "2026-05-20", 71907.0),
    ("Plamen Petrov", "2026-01-14", 30000.0),
    ("Halil Erseven", "2026-07-10", 10866.56),
    ("Halil Erseven", "2026-07-10", 11035.44),
]

for name, d, a in CASES:
    print(f"\n=== {name} | {d} | {a} ===")
    for m in ("account.payment", "account.move"):
        try:
            rows = c.search_read(m, [("date", "=", d), ("amount_total" if m == "account.move" else "amount", "=", a)],
                                 fields=(["name", "partner_id", "property_id", "ref", "move_type"] if m == "account.move"
                                         else ["name", "partner_id", "property_id", "journal_id"]), limit=10)
        except Exception as e:
            print("  ERR", m, e)
            continue
        for r in rows:
            part = (r.get("partner_id") or [None, None])[1]
            if part and name.split()[-1].lower() not in str(part).lower() and str(part) != name:
                continue
            print(f"  [{m}] {r['name']:<24} partner={str(part)[:45]:<45} prop={r.get('property_id')} ref={(r.get('ref') or '')[:34]}")

print("\n=== pgre contracts (OC refs) per customer ===")
for name in ("Andrii Levreshov", "Raphael", "Plamen Petrov", "Halil Erseven"):
    for m in ("property.contract", "sale.order"):
        try:
            rows = c.search_read(m, [("name", "ilike", name.split()[0])], fields=["name", "partner_id", "property_id", "state", "total_amount"], limit=6)
            if rows:
                print(f"\n  -- {name} via {m}:")
                for r in rows:
                    print("    ", {k: v for k, v in r.items() if k != "id"})
        except Exception as e:
            pass
