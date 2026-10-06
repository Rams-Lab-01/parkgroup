import openpyxl
WB = r'C:\Parkgroup Data\Consolidated_Sales_Workbook (4).xlsx'
wb = openpyxl.load_workbook(WB, data_only=True, read_only=True)
ws = wb['Unit Payment Collection']
for i, r in enumerate(ws.iter_rows(values_only=True)):
    if i < 8:
        print(i, [repr(v)[:40] for v in r[:6]])
    else:
        break
