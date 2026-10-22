import csv, os, re, json, sys
from collections import defaultdict, Counter

os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()

sname = lambda s: (re.match(r"^(.*?)\s*\(\d+\)$", s or "").group(1) if re.match(r"^(.*?)\s*\(\d+\)$", s or "") else s)
norm = lambda s: re.sub(r"\s+&\s+|/|\s+", " ", (s or "").lower()).strip()

rows = list(csv.DictReader(open("odoo_mcp/migration_out/payments.csv", newline="", encoding="utf-8-sig")))
by_partner = defaultdict(list)
for r in rows:
    by_partner[norm(sname(r["partner_id"]))].append(r)

blk = list(csv.DictReader(open(os.environ["TEMP"] + r"\opencode\blank124.csv", newline="", encoding="utf-8-sig")))
link = json.load(open("odoo_mcp/blank124_linkage/linkage.json", encoding="utf-8"))
exact = {l["pid"]: l for l in link["exact"]}

# collect all old property references per target partner
prop_refs = defaultdict(list)   # norm partner -> [old product.template display str]
for b in blk:
    pc = norm(b["partner"])
    # exact-match old records FIRST
    if b["id"] in exact:
        pass
    for r in by_partner.get(pc, []):
        p = r["property_id"]
        if p and p != "False":
            prop_refs[pc].append(p)

prop_ids = sorted({int(re.search(r"\((\d+)\)", p).group(1)) for ps in prop_refs.values() for p in ps if "(" in p})
props = c.read("product.template", prop_ids, ["name", "property_category_id", "project_id", "master_community", "unit_type"]) if prop_ids else []
prop_map = {}
for p in props:
    rec = {"name": p["name"],
           "cat": (p.get("property_category_id") or [None, None])[1],
           "unit_type": p.get("unit_type"),
           "community": p.get("master_community"),
           }
    if p.get("project_id"):
        rec["project"] = p["project_id"][1]
    prop_map[p["id"]] = rec
print("old units fetched:", len(props))
for pid, rec in list(prop_map.items())[:15]:
    print(f"  {pid}: {rec}")

# per target partner: pgre unit consensus
report = []
for b in blk:
    pc = norm(b["partner"])
    units = [sname(u) for u in prop_refs.get(pc, [])]
    ucnt = Counter(units)
    report.append({"pid": b["id"], "ref": b["payment_ref"], "partner": b["partner"],
                   "date": b["paid_on"], "amount": b["amount"], "tgt_unit": b["old_unit"],
                   "exact_old": b["id"] in exact,
                   "old_units_seen": dict(ucnt),
                   "unique_old_unit": ucnt and len(ucnt) == 1,
                   "old_unit_top": ucnt.most_common(1)[0][0] if ucnt else None})

single = [r for r in report if r["unique_old_unit"]]
multi  = [r for r in report if r["old_units_seen"] and not r["unique_old_unit"]]
none_  = [r for r in report if not r["old_units_seen"]]
print(f"blanked-124 rows whose pgre partner history yields a single unambiguous unit : {len(single)}")
print(f"rows with >1 unit in pgre partner history: {len(multi)}")
print(f"rows with no pgre property evidence at all: {len(none_)}")

json.dump({"report": report, "prop_map": {str(k): v for k, v in prop_map.items()}},
          open("odoo_mcp/blank124_linkage/report_v1.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

with open(os.environ["TEMP"] + r"\opencode\units_needed.txt", "w", encoding="utf-8") as fh:
    for r in report:
        fh.write(json.dumps(r) + "\n")
print("wrote per-row table", len(report))
