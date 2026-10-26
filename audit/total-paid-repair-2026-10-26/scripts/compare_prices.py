"""Compare prod unit prices with the reconciled workbook's sold value."""
import csv
import io

PROJ = {"BR1": "PBR1", "BR2": "PBR2", "RES": "PRY", "GOLF": "PGV"}

wb = list(csv.DictReader(io.open(r"C:\Users\USER\AppData\Local\Temp\pg\workbook_prices.csv", encoding="utf-8-sig")))
prod = list(csv.DictReader(io.open(r"C:\Users\USER\AppData\Local\Temp\pg\prod_units3.csv", encoding="utf-8-sig")))

wb_by = {}
for r in wb:
    sold = r["sold"] or ""
    lst = r["list_price"] or ""
    if sold:
        wb_by[(r["project"], str(r["unit_no"]).strip())] = float(sold)
    elif lst:
        wb_by[(r["project"], str(r["unit_no"]).strip())] = float(lst)

mismatch, missing, ok = [], [], 0
for p in prod:
    key = (PROJ.get(p["project_code"]), (p["unit_number"] or "").strip())
    if key[0] is None:
        continue
    want = wb_by.get(key)
    have = float(p.get("sale_price") or p.get("price") or 0)
    if want is None:
        missing.append((key, p["id"], p["name"], have))
        continue
    if abs(want - have) > 1.0:
        mismatch.append((key, p["id"], p["name"], have, want, want - have))
    else:
        ok += 1

print(f"prod units matched to a workbook price: {ok} equal, {len(mismatch)} different, {len(missing)} not in workbook")
print("\n-- prod price differs from the workbook --")
for key, pid, name, have, want, diff in sorted(mismatch, key=lambda x: -abs(x[5]))[:25]:
    print(f"  {key[0]} unit {key[1]:>4} (prod id {pid:>4}) {name[:34]:36} prod {have:>14,.2f}  workbook {want:>14,.2f}  diff {diff:>14,.2f}")
print("\n-- prod units with no workbook row --")
for key, pid, name, have in missing[:15]:
    print(f"  {key[0]} unit {key[1]:>4} (prod id {pid:>4}) {name[:34]:36} prod {have:>14,.2f}")

with io.open(r"C:\Users\USER\AppData\Local\Temp\pg\price_crosscheck.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh)
    w.writerow(["project", "unit_no", "prod_unit_id", "prod_name", "prod_price", "workbook_price", "diff"])
    for key, pid, name, have, want, diff in mismatch:
        w.writerow([key[0], key[1], pid, name, have, want, diff])
print("\nwritten price_crosscheck.csv")
