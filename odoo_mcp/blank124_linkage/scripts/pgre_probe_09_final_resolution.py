import csv, os, re, json
from collections import defaultdict, Counter
from datetime import date as D

os.environ["PYTHONIOENCODING"] = "utf-8"
sname = lambda s: (re.match(r"^(.*?)\s*\(\d+\)$", s or "").group(1) if re.match(r"^(.*?)\s*\(\d+\)$", s or "") else s)
norm = lambda s: re.sub(r"\s+&\s+|/|\s+", " ", (s or "").lower()).strip()

def dparse(s):
    try:
        return D(*map(int, s.split("-")))
    except Exception:
        return None

pmts = list(csv.DictReader(open("odoo_mcp/migration_out/payments.csv", newline="", encoding="utf-8-sig")))
by_pa = defaultdict(list)
by_partner = defaultdict(list)
for r in pmts:
    pc = norm(sname(r["partner_id"]))
    by_pa[(pc, round(float(r["amount"]), 2))].append(r)
    by_partner[pc].append(r)

crm = json.load(open("odoo_mcp/blank124_linkage/crm_leads.json", encoding="utf-8"))
crm_units = json.load(open("odoo_mcp/blank124_linkage/crm_units.json", encoding="utf-8"))
link = json.load(open("odoo_mcp/blank124_linkage/linkage.json", encoding="utf-8"))
exact_link = {l["pid"]: l for l in link["exact"]}

blk = list(csv.DictReader(open(os.environ["TEMP"] + r"\opencode\blank124.csv", newline="", encoding="utf-8-sig")))

COMM2PROJ = {"PARK BEACH RESIDENCE": "Park Beach Residence I", "PARK BEACH RESIDENCE II": "Park Beach Residence II",
             "INTERNATIONAL CITY (WARSAN FOURTH)": "Park Residency"}

def tgt_no_of(s):
    m = re.search(r"(\d+)(?!.*\d)", s or "")
    return m and m.group(1)

def unit_id_from_prop(p):
    """'[314] 314 (2216)' -> ('314', product id 2216)"""
    if not p or p == "False":
        return None
    m = re.match(r"\[(\d+)\]", p)
    pid = re.search(r"\((\d+)\)", p)
    return (m.group(1) if m else None, int(pid.group(1)) if pid else None)

# pgre product.template ids -> (unit_no, community/project)
prod_ids = {unit_id_from_prop(r["property_id"])[1] for r in pmts if unit_id_from_prop(r["property_id"])}
pids_seen = {int(k) for k in crm_units}
prod_all = sorted(prod_ids | pids_seen)
import json as j, sys, os as _os
_os.environ.update({k: v.strip() for k, v in (l.split("=",1) for l in open("odoo_mcp/.env") if "=" in l and not l.startswith("#")) if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402
c = OdooClient()
props = c.read("product.template", prod_all, ["name", "master_community", "project_id"])
PM = {p["id"]: {"unit_no": p["name"], "community": p.get("master_community"),
                "proj": p.get("project_id") and p["project_id"][1]} for p in props}
print("product universe:", len(PM))

rows_out = []
stats = Counter()
for b in blk:
    pc = norm(b["partner"])
    amt = round(float(b["amount"]), 2)
    td = dparse(b["paid_on"])
    ev = {}
    # 1) per-payment pgre row
    cands = by_pa.get((pc, amt), [])
    picked, pk = None, 99
    for r in cands:
        od = dparse(r["date"])
        dd = abs((od - td).days) if (od and td) else 99999
        uid = unit_id_from_prop(r["property_id"])
        u = uid and uid[0]
        agree = (u == tgt_no_of(b["old_unit"]))
        # scoring: same day + unit agrees wins; else same day; else nearest date with agree
        score = dd - (1000 if (dd == 0 and agree) else (500 if (dd <= 200 and agree) else 0))
        if score < pk:
            picked, pk = r, score
    best, best_d = picked, None
    row_ev = None
    unit = None
    if picked is not None:
        od = dparse(picked["date"])
        best_d = abs((od - td).days) if (od and td) else 99999
        if od and td and best_d <= 200:
            uid = unit_id_from_prop(picked["property_id"])
            row_ev = {"old_payment": picked["old_id"], "old_date": picked["date"], "d_days": best_d,
                      "old_amount": round(float(picked["amount"]), 2), "unit": uid}
            if uid:
                unit = uid[0]
                ev["how"] = ("exact-day-agree" if best_d == 0 and uid[0] == tgt_no_of(b["old_unit"])
                             else ("exact-day-diff" if best_d == 0 else "near%d" % best_d))
    # 2) partner-level fallbacks
    hist_units = Counter()
    hist_pid = {}
    for r in by_partner.get(pc, []):
        uid = unit_id_from_prop(r["property_id"])
        if uid:
            hist_units[uid[0]] += 1
            hist_pid.setdefault(uid[0], uid[1])
    crm_units_v = sorted({(u.get("name"), u.get("community")) for lrow in crm.get(b["partner"], []) for u in [lrow["property"]] if u})

    final = None
    src = None
    if unit:
        final, src = unit, ev.get("how", "pgre-payment")
    elif len(hist_units) == 1:
        final, src = next(iter(hist_units)), "pgre-partner-single"
    elif len(crm_units_v) == 1:
        final, src = crm_units_v[0][0], "pgre-crm-single"
    if final:
        stats[src] += 1
    else:
        stats["unresolved"] += 1

    # agreement with target's pre-blank unit
    tgt_no = tgt_no_of(b["old_unit"])
    agree = (tgt_no == final) if final else None
    proj_guess = None
    if final:
        cmty = None
        pid_ = ev and row_ev and row_ev["unit"] and row_ev["unit"][1]
        if not pid_:
            pid_ = hist_pid.get(final)
        if pid_ and int(pid_) in PM:
            cmty = PM[int(pid_)]["community"]
        if not cmty:
            for _, rec in PM.items():        # CRM-only units fallback
                if rec["unit_no"] == final and rec["community"]:
                    cmty = rec["community"]
                    break
        proj_guess = COMM2PROJ.get(cmty, cmty)
    rows_out.append({"pid": b["id"], "ref": b["payment_ref"], "partner": b["partner"], "date": b["paid_on"],
                     "amount": amt, "tgt_project": (b["old_unit"].split(" - ", 1) + [None])[0], "tgt_unit_no": tgt_no,
                     "resolve": src, "unit_final": final, "pgre_community": proj_guess,
                     "agree_with_old": agree,
                     "crm_units": "/".join(f"{u[0]}@{u[1]}" for u in crm_units_v),
                     "hist_units": ",".join(f"{k}x{v}" for k, v in hist_units.items()),
                     "ev": json.dumps(row_ev, default=str) if row_ev else None})

json.dump(rows_out, open("odoo_mcp/blank124_linkage/final_rows.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open("odoo_mcp/blank124_linkage/final_rows.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows_out[0]))
    w.writeheader()
    w.writerows(rows_out)

print("resolution stats:", dict(stats))
vsum = defaultdict(lambda: {"n": 0, "ok": 0, "mismatch": [], "units": set()})
for r in rows_out:
    v = vsum[r["partner"]]
    v["n"] += 1
    if r["unit_final"]:
        v["ok"] += 1
        v["units"].add("%s<%s>" % (r["unit_final"], r["pgre_community"] or "PGRE"))
        if r["agree_with_old"] is False:
            v["mismatch"].append((r["pid"], r["tgt_unit_no"], r["unit_final"]))
print()
for v, s in vsum.items():
    print(f"{v[:60]:<60} n={s['n']:>3} resolved={s['ok']:>3} units={sorted(s['units'])}")
    for mm in s["mismatch"][:6]:
        print("    tgt", mm[1], "-> pgre", mm[2], "(pid", mm[0], ")")
