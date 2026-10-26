"""Cross-check every prod unit price against the owner's reconciled sales workbook.

Each sales sheet names its columns differently; the aliases below cover them.
The workbook's sale price (after discount) must equal prod's
property_details.sale_price, and the instalment plan must be built on it.
"""
import csv
import io
import re

import openpyxl

SHEETS = [
    ("data/PBR1 Sales.xlsx", "PBR1",
     dict(unit=("UNIT",), sold=("Sold Value", "Sale Price"), list_=("UNIT PRICE", "List Price"),
          disc=("Discount Amount",))),
    ("data/PBR2 Sales.xlsx", "PBR2",
     dict(unit=("Unit No.", "UNIT"), sold=("Sale Price", "Sold Value", "Net Sale Price"),
          list_=("List Price", "New PSF"), disc=("Discount Amount",))),
    ("data/PRY-Sales Sheet.xlsx", "PRY",
     dict(unit=("Unit Number", "Unit No.", "UNIT"), sold=("Sale Price", "Sold Value"),
          list_=("List Price",), disc=("Discount Amount",))),
    ("data/PGV Sales.xlsx", "PGV",
     dict(unit=("Unit  No", "Unit No.", "UNIT"), sold=("Sold Value", "Sale Price"),
          list_=("List Price  AED", "List Price"), disc=("Discount",))),
]


def norm(s):
    if s is None:
        return ""
    if not isinstance(s, str):
        s = str(s)
    return re.sub(r"\s+", " ", s.strip())


def fnum(v):
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, TypeError):
        return None


def find_header(rows, alias_list):
    for i, r in enumerate(rows):
        vals = [norm(v) for v in r]
        for a in alias_list:
            if a in vals:
                return i
    return None


rows_out = []
for path, sheet, alias in SHEETS:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if sheet not in wb.sheetnames:
        wb.close()
        continue
    data = list(wb[sheet].iter_rows(values_only=True))
    wb.close()
    hidx = find_header(data, alias["unit"])
    if hidx is None:
        print("no header for", path)
        continue
    cols = [norm(v) for v in data[hidx]]

    def col(names):
        for n in names:
            if n in cols:
                return cols.index(n)
        return None

    cu, cs, cl, cd = (col(alias["unit"]), col(alias["sold"]), col(alias["list_"]), col(alias["disc"]))
    n = 0
    for r in data[hidx + 1:]:
        vals = list(r) + [None] * (len(cols) - len(r))
        u = norm(vals[cu]) if cu is not None and cu < len(vals) else ""
        m = re.search(r"(\d+)", u)
        if not m:
            continue
        sold = fnum(vals[cs]) if cs is not None and cs < len(vals) else None
        lst = fnum(vals[cl]) if cl is not None and cl < len(vals) else None
        disc = fnum(vals[cd]) if cd is not None and cd < len(vals) else None
        if sold is None and lst is None:
            continue
        rows_out.append(dict(project=sheet, unit_no=m.group(1), sold=sold, list_price=lst,
                             discount=disc, unit_cell=u))
        n += 1
    print(f"{path} [{sheet}]: {n} priced units")

with io.open(r"C:\Users\USER\AppData\Local\Temp\pg\workbook_prices.csv", "w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows_out[0].keys()))
    w.writeheader()
    w.writerows(rows_out)
print("written workbook_prices.csv;", len(rows_out), "rows")
