import csv, os, sys
from pathlib import Path

dotenv = {}
for line in Path("odoo_mcp/.env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        dotenv[k.strip()] = v.strip()

os.environ.update({k: v for k, v in dotenv.items() if k.startswith("PGRE_")})
sys.path.insert(0, "odoo_mcp")
from pgre_client import OdooClient  # noqa: E402

c = OdooClient()
print("auth:", c)

# payment refs from the blanked-124 CSV
refs = []
with open(os.environ["TEMP"] + r"\opencode\blank124.csv", newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
        if row["payment_ref"] not in ("-", ""):
            refs.append((row["id"], row["payment_ref"], row["partner"], row["amount"]))
refs = list(dict.fromkeys(refs))
names = [r[1] for r in refs]
print("refs:", len(names), "unique:", len(set(names)))

# how many exist in pgre by exact name
hits = c.search_read("account.payment", [("name", "in", names)],
                     fields=["name", "partner_id", "amount", "date", "payment_type", "journal_id", "state"],
                     limit=500)
print("matches in pgre:", len(hits))
for h in hits[:8]:
    print(h)
