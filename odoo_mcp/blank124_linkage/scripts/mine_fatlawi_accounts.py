import csv, os, re, sys, io
from collections import Counter, defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sname = lambda s: (re.match(r"^(.*?)\s*\(\d+\)$", s or "").group(1) if re.match(r"^(.*?)\s*\(\d+\)$", s or "") else s)
norm = lambda s: re.sub(r"\s+&\s+|/|\s+", " ", (s or "").lower()).strip()
FA = "Mohammed Jassim Mohammed Al Fatlawi"

def rows_of(fn):
    return list(csv.DictReader(open(f"odoo_mcp/migration_out/{fn}", newline="", encoding="utf-8-sig")))

# --- invoices for Fatlawi ---
inv = rows_of("invoices.csv")
print("invoices total:", len(inv))
fa_inv = [r for r in inv if norm(sname(r.get("partner_id", ""))) == norm(FA)]
print("\n=== pgre INVOICES for Fatlawi:", len(fa_inv), "===")
for r in sorted(fa_inv, key=lambda x: x.get("date") or ""):
    print(f"  old_id={r['old_id']:>6} {r.get('date')} {r.get('name','')[:26]:<26} type={r.get('move_type',''):<11} "
          f"untaxed={r.get('amount_untaxed',''):>10} total={r.get('amount_total',''):>10} paid={r.get('amount_paid',''):>10} "
          f"state={r.get('state',''):<8} prop={r.get('property_id',''):<20} ref={(r.get('ref') or '')[:18]}")
print("\ninvoice fields mentioning 309/307/310 in free text for Fatlawi:")
for r in fa_inv:
    blob = " ".join(str(v) for v in r.values() if v and v != "False")
    for tok in ("309", "307", "310"):
        if re.search(r"\b" + tok + r"\b", blob):
            print("   ", r["old_id"], r.get("name"), "contains", tok, "| prop:", r.get("property_id"))
            break

# --- journal entries for Fatlawi ---
je = rows_of("journal_entries.csv")
print("\njournal_entries total:", len(je))
cols = [c for c in je[0] if c in ("old_id", "name", "date", "journal_id", "partner_id", "ref", "memo", "amount_total", "move_type", "state")]
print("cols used:", cols)
fa_je = [r for r in je if norm(sname(r.get("partner_id", ""))) == norm(FA)]
print("\n=== pgre JOURNAL ENTRIES for Fatlawi:", len(fa_je), "===")
for r in sorted(fa_je, key=lambda x: x.get("date") or "")[-40:]:
    print(f"  {r.get('date')} {r.get('journal_id','')[:30]:<30} {r.get('name','')[:22]:<22} amt={r.get('amount_total',''):>10} "
          f"ref={(r.get('ref') or '')[:16]:<16} memo={(r.get('memo') or '')[:40]}")
