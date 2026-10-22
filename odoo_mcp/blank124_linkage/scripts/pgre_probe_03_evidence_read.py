import csv, os, re, json, sys
from collections import defaultdict, Counter

os.environ.update({k: v.strip() for k, v in
                   (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#"))
                   if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402

linkage = json.load(open("odoo_mcp/blank124_linkage/linkage.json", encoding="utf-8"))
sname = lambda s: (re.match(r"^(.*?)\s*\(\d+\)$", s or "").group(1) if re.match(r"^(.*?)\s*\(\d+\)$", s or "") else s)

# old rows again for the loose candidates' full context
rows = {}
with open("odoo_mcp/migration_out/payments.csv", newline="", encoding="utf-8-sig") as fh:
    for r in csv.DictReader(fh):
        rows[r["old_id"]] = r

def enrich(b, m):
    return {"pid": b["pid"], "ref": b["ref"], "partner": b["partner"],
            "date": b["date"], "amount": b["amount"], "target_unit": b["old_unit"],
            "tgt_journal": b["journal"],
            "old_id": m["old_id"], "old_name": m["name"], "old_date": m["date"],
            "old_property": m["property_id"], "old_journal": m["journal_id"],
            "old_payref": m["payment_reference"], "old_memo": m["memo"],
            "old_realestate": m["real_estate_ref"], "old_receipt_title": m["payment_receipt_title"],
            "old_user": m["sales_user_id"], "old_team": m["sales_team_id"],
            "old_inv_kind": m["reconciled_invoices_type"],
            "jour_ok": sname(m["journal_id"]) == b["journal"]}

for item in linkage["loose"]:
    cands = item["cands"]
    item["detail"] = [enrich({**item, "cands": None}, rows[str(c["old_id"])]) for c in cands]

# which fields on old account.payment: relation of property_id
c = OdooClient()
fg = c.search_read("ir.model.fields", [("model", "=", "account.payment"), ("name", "in", ["property_id", "reservation_id", "real_estate_ref"])],
                   fields=["name", "relation", "ttype"], limit=10)
print("old payment field relations:", fg)

# exact cases first, then loose
cases = []
for x in linkage["exact"]:
    cases.append({"kind": "exact", "date_ok": True, **x})
loose_cases = []
for item in linkage["loose"]:
    d = item["detail"][0]
    drift = None
    try:
        from datetime import date
        y1, m1, dd1 = map(int, item["date"].split("-")); y2, m2, dd2 = map(int, d["old_date"].split("-"))
        drift = (date(y1, m1, dd1) - date(y2, m2, dd2)).days
    except Exception:
        pass
    loose_cases.append({"kind": "loose", "n_cands": len(item["detail"]), "drift_days": drift,
                        **{k: v for k, v in item.items() if k not in ("cands", "detail")}, "old": d})

print("loose journal agreement:", sum(1 for x in loose_cases if x["old"]["jour_ok"]), "/", len(loose_cases))
print("loose date drift distribution:", Counter(x["drift_days"] for x in loose_cases).most_common(12))

# old property ids involved
pids = set()
for x in cases:
    if x["old_property"] not in ("False", None, ""):
        pids.add(x["old_property"])
for x in loose_cases:
    p = x["old"]["old_property"]
    if p not in ("False", None, ""):
        pids.add(p)

# infer old property model & read them live
rels = [f for f in fg if f["name"] == "property_id"]
if rels and pids:
    rel = rels[0]["relation"]
    ids = sorted({int(re.search(r"\((\d+)\)", p).group(1)) for p in pids if "(" in p})
    props = c.read(rel, ids, ["name", "code", "property_project_id", "project_id"])
    print(f"\nold properties on {rel}: {len(props)}")
    for p in props[:40]:
        print(" ", p)

json.dump({"exact": cases, "loose": loose_cases}, open("odoo_mcp/blank124_linkage/enriched.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nsaved odoo_mcp/blank124_linkage/enriched.json")
