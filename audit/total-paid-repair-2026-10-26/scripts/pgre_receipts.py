"""Read-only: PGRE inbound receipts per partner name -> pgre_receipts.csv"""
import csv, re
from collections import defaultdict
from pgre_env import c
norm = lambda s: re.sub(r"\s+", " ", (s or "").strip().lower())
tot, cnt = defaultdict(float), defaultdict(int)
for p in c.iter_search_read("account.payment", [("payment_type", "=", "inbound"),
                            ("state", "not in", ["draft", "canceled", "cancel", "rejected"])],
                            ["partner_id", "amount"]):
    k = norm((p["partner_id"] or [0, ""])[1])
    tot[k] += p["amount"]; cnt[k] += 1
with open("pgre_receipts.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh); w.writerow(["partner", "pgre_receipts", "n"])
    for k in tot: w.writerow([k, round(tot[k], 2), cnt[k]])
print(len(tot), "partners,", sum(cnt.values()), "receipts, total", f"{sum(tot.values()):,.2f}")
