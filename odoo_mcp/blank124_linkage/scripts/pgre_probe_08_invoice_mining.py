import csv, os, re, json
from collections import defaultdict, Counter

sname = lambda s: (re.match(r"^(.*?)\s*\(\d+\)$", s or "").group(1) if re.match(r"^(.*?)\s*\(\d+\)$", s or "") else s)
norm = lambda s: re.sub(r"\s+&\s+|/|\s+", " ", (s or "").lower()).strip()

pmts = list(csv.DictReader(open("odoo_mcp/migration_out/payments.csv", newline="", encoding="utf-8-sig")))
by_partner = defaultdict(list)
for r in pmts:
    by_partner[norm(sname(r["partner_id"]))].append(r)

vendors = ["Imaan Mangal", "Chitalwala Naseema Hakimuddin / Rajab Ali Mukadam / Hasan Abuzer Tata Wala",
           "Kim Sandra Naulls & Jack Phillip John Bines", "Mohammed Jassim Mohammed Al Fatlawi"]

for v in vendors:
    pc = norm(v)
    rows = by_partner.get(pc, [])
    print(f"\n== {v[:60]} : {len(rows)} old payments")
    for r in sorted(rows, key=lambda x: (x["date"], x["name"])):
        print(f"   {r['old_id']:>6} {r['date']} {float(r['amount']):>10.2f} {r['name']:<24} "
              f"prop={r['property_id']:<22} resv={r['reservation_id']:<8} title={r['payment_receipt_title']:<18} "
              f"payref={r['payment_reference'][:36] or '-'} re_est={r['real_estate_ref'][:40] or '-'}")

# invoice header / property fields?
inv = list(csv.DictReader(open("odoo_mcp/migration_out/invoices.csv", newline="", encoding="utf-8-sig")))
cols = list(inv[0])
print("\ninvoices.csv columns:", cols[:24], "... total cols", len(cols))
pcols = [c_ for c_ in cols if "proper" in c_ or "unit" in c_ or "project" in c_ or "contract" in c_ or "reserv" in c_]
print("unit-ish invoice columns:", pcols)
