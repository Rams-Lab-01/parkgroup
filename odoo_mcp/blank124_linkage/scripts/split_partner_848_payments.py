import os, sys, io, csv, re
from collections import Counter, defaultdict
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sname = lambda s: (re.match(r"^(.*?)\s*\(\d+\)$", s or "").group(1) if re.match(r"^(.*?)\s*\(\d+\)$", s or "") else s)
pmts = list(csv.DictReader(open("odoo_mcp/migration_out/payments.csv", newline="", encoding="utf-8-sig")))
by_key = defaultdict(list)
for r in pmts:
    by_key[(sname(r["partner_id"]), r["date"], round(float(r["amount"]), 2))].append(r)

def classify(partner_name, date, amount):
    k = (partner_name, date, round(amount, 2))
    cands = by_key.get(k, [])
    if not cands:
        return "no-pgre-match"
    names = {c["partner_id"] for c in cands}
    if any("Fatlawi" in n for n in names):
        return "pgre-878-Fatlawi"
    if any("Watson" in n for n in names):
        return "pgre-1223-Watson&Singh"
    return "pgre-other:" + "|".join(sorted(names))[:60]

tgt = list(csv.DictReader(open(os.environ["TEMP"] + r"\opencode\partner848.csv", newline="", encoding="utf-8-sig")))
by_pid = defaultdict(list)
for t in tgt:
    by_pid[t["partner_id"]].append(t)

# pgre name variants for the two target partners (email/phone identical in pgre)
NAMES = {"848": ["Mohammed Jassim Mohammed AL Fatlawi", "Ian Richard Watson & Gurmuke John Singh"],
         "847": ["Ian Richard Watson ", "Ian Richard Watson & Gurmuke John Singh",
                 " Ian Richard Watson / Gurmuke John Singh "]}
for pid, rows in sorted(by_pid.items()):
    cnt = Counter()
    detail = defaultdict(list)
    for t in rows:
        hit = None
        for nm in NAMES.get(pid, []):
            c = classify(nm, t["date"], float(t["amount"]))
            if c != "no-pgre-match":
                hit = c
                break
        hit = hit or "no-pgre-match"
        cnt[hit] += 1
        detail[hit].append((t["id"], t["date"], t["amount"], t["unit_number"], t["project"]))
    print(f"\n== target partner {pid}: {len(rows)} payments")
    for k, v in cnt.most_common():
        units = sorted({u for _, _, _, u, _ in detail[k]})
        amt = sum(float(a) for _, _, a, _, _ in detail[k])
        print(f"   {k:<34} n={v:<4} total={amt:>12.2f} units={units}")
        if k == "no-pgre-match":
            for d in detail[k][:8]:
                print("        unmatched:", d)
