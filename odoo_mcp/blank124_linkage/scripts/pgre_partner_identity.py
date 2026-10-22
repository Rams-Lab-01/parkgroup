import os, sys, io, csv, re
from collections import Counter, defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

print("=== pgre partners named Fatlawi ===")
for p in c.search_read("res.partner", [("name", "ilike", "Fatlawi")], fields=["name", "email", "phone", "is_company", "parent_id", "active"], limit=20):
    print("  ", p)

print("\n=== pgre partners with email mbj2080@gmail.com ===")
for p in c.search_read("res.partner", [("email", "=ilike", "mbj2080@gmail.com")], fields=["name", "email", "phone", "parent_id", "active"], limit=20):
    print("  ", p)

print("\n=== pgre partners with phone 09715 22 61059 / +971502261059 ===")
for dom in ([("phone", "ilike", "971502261059")], [("phone", "ilike", "09715 22 61059")]):
    for p in c.search_read("res.partner", dom, fields=["name", "email", "phone", "parent_id"], limit=20):
        print("  ", dom, "->", p)

print("\n=== pgre: partner ids of the 12 Watson receipts (28000 series) ===")
for d, a in [("2026-08-11", 28000.0), ("2025-10-16", 277418.6), ("2026-09-14", 28000.0)]:
    rows = c.search_read("account.payment", [("date", "=", d), ("amount", "=", a)], fields=["name", "partner_id", "property_id"], limit=5)
    for r in rows:
        print(f"   {d} {a} -> {r['name']} partner_id={r['partner_id']}")

print("\n=== split of the 69 target payments on partner 848 (pgre matching) ===")
sname = lambda s: (re.match(r"^(.*?)\s*\(\d+\)$", s or "").group(1) if re.match(r"^(.*?)\s*\(\d+\)$", s or "") else s)
pmts = list(csv.DictReader(open("odoo_mcp/migration_out/payments.csv", newline="", encoding="utf-8-sig")))
by_pa = defaultdict(list)
for r in pmts:
    by_pa[(sname(r["partner_id"]), r["date"], round(float(r["amount"]), 2))].append(r)
fat = {k: v for k, v in by_pa.items() if "Fatlawi" in k[0]}
wat = {k: v for k, v in by_pa.items() if "Watson" in k[0]}
tgt = list(csv.DictReader(open(os.environ["TEMP"] + r"\opencode\partner848.csv", newline="", encoding="utf-8-sig")))
print("target rows loaded:", len(tgt))
cnt = Counter()
unmatched = []
for t in tgt:
    k = (t["partner"], t["date"], round(float(t["amount"]), 2))
    if k in fat:
        cnt["pgre-Fatlawi"] += 1
    elif k in wat:
        cnt["pgre-Watson"] += 1
    else:
        cnt["no-pgre-match"] += 1
        unmatched.append(t)
print("split:", dict(cnt))
print("\nunmatched sample:")
for t in unmatched[:15]:
    print("   ", t["id"], t["date"], t["amount"], t["unit_number"], t["project"], t["name"])
