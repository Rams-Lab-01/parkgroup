import json, csv, io, sys
from collections import Counter, defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

COMM2PROJ = {"PARK BEACH RESIDENCE": "Park Beach Residence I",
             "PARK BEACH RESIDENCE II": "Park Beach Residence II",
             "INTERNATIONAL CITY (WARSAN FOURTH)": "Park Residency"}

rows = json.load(open("odoo_mcp/blank124_linkage/final_rows.json", encoding="utf-8"))

# --- the 12 rows resolved via pgre amount+day match to a DIFFERENT pgre partner
# (Ian Richard Watson & Gurmuke John Singh) whose receipts sit on unit 309
# @ PARK BEACH RESIDENCE II (pgre product.template 2211, type 2 BED)
WATSON = {
    "3933": ("2026-08-11", 28000.0, "PCSH6/2026/00241"),
    "4149": ("2026-09-14", 28000.0, "PCSH6/2026/00271"),
    "4661": ("2026-07-14", 28000.0, "PCSH6/2026/00077"),
    "4662": ("2026-06-18", 28000.0, "PCSH6/2026/00076"),
    "4663": ("2026-05-15", 28000.0, "PCSH6/2026/00075"),
    "4664": ("2026-03-24", 28000.0, "PCSH6/2026/00074"),
    "4665": ("2026-03-18", 28000.0, "PCSH6/2026/00073"),
    "4666": ("2026-02-13", 27970.0, "PCSH6/2026/00072"),
    "4667": ("2026-01-30", 27470.0, "PCSH6/2026/00071"),
    "4668": ("2026-01-09", 27470.0, "PCSH6/2026/00070"),
    "4669": ("2025-12-16", 271419.0, "PCSH6/2025/00162"),
    "4670": ("2025-10-16", 277418.6, "PCSH8/2025/00050"),
}

exp = []
for r in rows:
    pid = r["pid"]
    if pid in WATSON:
        d, a, pname = WATSON[pid]
        assert abs(r["amount"] - a) < 0.005 and r["date"] == d, (pid, r["amount"], r["date"])
        r["unit_final"] = "309"
        r["pgre_community"] = "PARK BEACH RESIDENCE II"
        r["resolve"] = "pgre-watson-exact-amount-day"
        r["crm_units"] = "309@PARK BEACH RESIDENCE II (lead 309, SPA, Watson & Singh)"
        r["ev"] = json.dumps({"pgre_payment": pname, "pgre_partner": "Ian Richard Watson & Gurmuke John Singh",
                              "pgre_property": "[309] 309 (2211)", "pgre_community": "PARK BEACH RESIDENCE II",
                              "note": "target partner_id points to Fatlawi (848) - partner data issue, unit confirmed"})
    if not r["unit_final"]:
        print("STILL UNRESOLVED:", pid, r["partner"], r["amount"], r["date"])
        continue
    proj = COMM2PROJ.get(r["pgre_community"], r["pgre_community"])
    exp.append({"pid": pid, "expected_unit_no": r["unit_final"], "expected_project": proj,
                "evidence": r["resolve"], "partner": r["partner"], "amount": r["amount"], "date": r["date"]})

print("expected rows:", len(exp))
print("by evidence:", Counter(e["evidence"] for e in exp))
print("by project:", Counter(e["expected_project"] for e in exp))

with open("odoo_mcp/blank124_linkage/relink_expected.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(exp[0]))
    w.writeheader(); w.writerows(exp)

# refreshed full report
full = []
for r in rows:
    full.append({"pid": r["pid"], "payment_ref": r["ref"], "partner": r["partner"], "date": r["date"],
                 "amount": r["amount"], "old_unit_before_blank": "%s - unit %s" % (r["tgt_project"] or "-", r["tgt_unit_no"] or "-"),
                 "proposed_unit": r["unit_final"] or "", "proposed_project": COMM2PROJ.get(r["pgre_community"], r["pgre_community"]) or "",
                 "evidence": r["resolve"] or "unresolved", "pgre_evidence": r["ev"] or "", "crm": r["crm_units"]})
with open("odoo_mcp/blank124_linkage/relink_final_124.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(full[0]))
    w.writeheader(); w.writerows(full)
print("wrote relink_expected.csv + relink_final_124.csv")
