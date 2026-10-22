import csv, os, re, json
from collections import defaultdict

sname = lambda s: (re.match(r"^(.*?)\s*\(\d+\)$", s or "").group(1) if re.match(r"^(.*?)\s*\(\d+\)$", s or "") else s)
norm = lambda s: re.sub(r"\s+&\s+|/|\s+", " ", (s or "").lower()).strip()

rows = []
with open("odoo_mcp/migration_out/payments.csv", newline="", encoding="utf-8-sig") as fh:
    rows = list(csv.DictReader(fh))

by_partner = defaultdict(list)
for r in rows:
    by_partner[norm(sname(r["partner_id"]))].append(r)

blk = list(csv.DictReader(open(os.environ["TEMP"] + r"\opencode\blank124.csv", newline="", encoding="utf-8-sig")))
matched_ids = set()
for ln in json.load(open("odoo_mcp/blank124_linkage/linkage.json", encoding="utf-8"))["exact"]:
    matched_ids.add(ln["pid"])

no_hit = [b for b in blk if b["id"] not in matched_ids]
print("no-candidate target rows:", len(no_hit))

cov = 0
picked = sorted(no_hit, key=lambda x: x["partner"])[:12]
for b in picked:
    cands = by_partner.get(norm(b["partner"]), [])
    cov += bool(cands)
    print(f"\ntarget {b['id']} {b['payment_ref']} {b['partner']} {b['amount']} {b['paid_on']} [{b['journal']}]")
    if not cands:
        print("   -> pgre: partner ABSENT")
        continue
    for r in sorted(cands, key=lambda x: x["date"])[:4]:
        print(f"   pgre {r['old_id']:>6} {r['name']:<22} {r['date']} {r['amount']:>10} {sname(r['journal_id'])[:28]:<28} prop={r['property_id']}")
print("\npartners present in pgre within sample:", cov, "/", len(picked))
