import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

TARGET = [  # (target date, amount) of the 12 open rows
    ("2026-08-11", 28000.0), ("2026-09-14", 28000.0), ("2026-07-14", 28000.0),
    ("2026-06-18", 28000.0), ("2026-05-15", 28000.0), ("2026-03-24", 28000.0),
    ("2026-03-18", 28000.0), ("2026-02-13", 27970.0), ("2026-01-30", 27470.0),
    ("2026-01-09", 27470.0), ("2025-12-16", 271419.0), ("2025-10-16", 277418.6),
]
print("=== every pgre payment matching each of the 12 (date, amount) ===")
ok = 0
for d, a in TARGET:
    rows = c.search_read("account.payment", [("date", "=", d), ("amount", "=", a)],
                         fields=["name", "partner_id", "property_id", "journal_id", "state"], limit=10)
    hit = [r for r in rows if r.get("property_id") and "309" in str(r["property_id"])]
    for r in rows:
        print(f"  {d} {a:>10} -> {r['name']:<20} {str((r.get('partner_id') or ['',''])[1])[:42]:<42} "
              f"prop={str(r.get('property_id')):<26} {str((r.get('journal_id') or ['',''])[1])[:26]}")
    if hit:
        ok += 1
print(f"\nrows with a pgre counterpart on unit 309: {ok}/{len(TARGET)}")

print("\n=== pgre partner record for Watson & Singh (id, name, email, phone) ===")
ps = c.search_read("res.partner", [("name", "ilike", "Watson")], fields=["name", "email", "phone", "is_company", "parent_id", "commercial_partner_id"], limit=10)
for p in ps:
    print("  ", p)

print("\n=== pgre CRM leads of that partner (full) ===")
ls = c.search_read("crm.lead", [("partner_id.name", "ilike", "Watson")], fields=["name", "partner_id", "property_id", "stage_id", "type", "create_date", "probability", "expected_revenue", "description", "lead_properties"], limit=20)
for l in ls:
    print("  ", {k: v for k, v in l.items() if k not in ("id",)})
