import csv, os, re, json, sys
from collections import defaultdict, Counter

os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

norm = lambda s: re.sub(r"\s+&\s+|/|\s+", " ", (s or "").lower()).strip()

# what unit-ish fields exist on old crm.lead?
f = c.search_read("ir.model.fields", [("model", "=", "crm.lead")], fields=["name"], limit=400)
names = sorted(x["name"] for x in f)
print("crm.lead unit-ish fields:", [n for n in names if any(k in n for k in ("unit", "proper", "proj", "community", "reser", "contract"))])

# the 13 vendor names of the 124
blk = list(csv.DictReader(open(os.environ["TEMP"] + r"\opencode\blank124.csv", newline="", encoding="utf-8-sig")))
vendors = {}
for b in blk:
    key = b["partner"]
    if key not in vendors:
        vendors[key] = b
print("\nvendors:", len(vendors))

for vname, b in list(vendors.items())[:5] + list(vendors.items())[-3:]:
    dom = [("partner_id.name", "=ilike", vname)]
    leads = c.search_read("crm.lead", dom, fields=["name", "stage_id", "partner_id", "type", "probability", "create_date"], limit=10)
    print(f"\npartner {vname[:55]:<55} leads={len(leads)}")
    for l in leads[:3]:
        print(f"   crm.lead {l['id']} [{str(l['create_date'])[:10]}] {l['type']} {l['name'][:60]}")
