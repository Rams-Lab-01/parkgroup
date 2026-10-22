import csv, os, re, json, sys
from collections import defaultdict, Counter

os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

blk = list(csv.DictReader(open(os.environ["TEMP"] + r"\opencode\blank124.csv", newline="", encoding="utf-8")))
vendors = []
for b in blk:
    if b["partner"] not in vendors:
        vendors.append(b["partner"])

FIELDS = ["name", "property_id", "project_id", "prefered_unit_1_id", "prefered_unit_2_id", "prefered_unit_3_id",
          "pg_reservation_confirmed", "stage_id", "create_date", "type", "probability", "team_id", "user_id"]

# collect every lead id per vendor, then batch property/pt reads
out = {}
prop_ids = set()
for v in vendors:
    dom = ["|", ("partner_id.name", "=ilike", v), ("partner_id.name", "=ilike", " ".join(v.split())[:100])]
    leads = c.search_read("crm.lead", dom, fields=FIELDS, limit=50)
    out[v] = leads
    for l in leads:
        for f in ("property_id", "project_id", "prefered_unit_1_id", "prefered_unit_2_id", "prefered_unit_3_id"):
            if l[f] and len(l[f]) == 2:
                prop_ids.add(l[f][0])

props = c.read("product.template", sorted(prop_ids), ["name", "master_community", "project_id", "unit_type"]) if prop_ids else []
pm = {p["id"]: {"name": p["name"], "community": p["master_community"], "unit_type": p["unit_type"],
                "project": p.get("project_id") and p["project_id"][1]} for p in props}

report = {}
for v, leads in out.items():
    rows = []
    for l in leads:
        unit_0 = (pm.get(l["property_id"] and l["property_id"][0]) or {}).get("name")
        units_pref = [(pm.get(i, {}) or {}).get("name") for i in
                      [l["prefered_unit_1_id"][0] if l["prefered_unit_1_id"] else None,
                       l["prefered_unit_2_id"][0] if l["prefered_unit_2_id"] else None,
                       l["prefered_unit_3_id"][0] if l["prefered_unit_3_id"] else None] if i]
        rows.append({"lead": l["id"], "lname": l["name"], "date": str(l["create_date"])[:10],
                     "type": l["type"], "stage": (l["stage_id"] or [None, None])[1],
                     "prob": l["probability"], "proj": (pm.get(l["project_id"] and l["project_id"][0]) or {}).get("community"),
                     "res_confirmed": l["pg_reservation_confirmed"],
                     "property": (pm.get(l["property_id"] and l["property_id"][0]) or {}),
                     "preferred": [u for u in units_pref if u]})
    report[v] = rows

for v, rows in report.items():
    if not rows:
        print(f"\n== {v}\n   no CRM leads in pgre")
        continue
    print(f"\n== {v}  ({len(rows)} leads)")
    for r in rows:
        print(f"   lead{r['lead']:>4} [{r['date']}] '{r['lname']}' stage={r['stage']} proj={r['proj']} "
              f"unit={r['property'].get('name')}<{r['property'].get('community')}> pref={r['preferred']} res_conf={r['res_confirmed']}")

json.dump(report, open("odoo_mcp/blank124_linkage/crm_leads.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(pm, open("odoo_mcp/blank124_linkage/crm_units.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved crm_leads.json / crm_units.json")
