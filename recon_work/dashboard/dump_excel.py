import openpyxl
import sys

WB = r'C:\Parkgroup Data\Consolidated_Sales_Workbook (4).xlsx'
wb = openpyxl.load_workbook(WB, data_only=True, read_only=True)

STRIP = 40

def dump(name, maxrows=60):
    ws = wb[name]
    print('=' * 24, name, '=' * 24)
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        vals = [str(v).strip() if v is not None else '' for v in row]
        if any(vals):
            # collapse trailing empties
            while vals and vals[-1] == '':
                vals.pop()
            print(' | '.join(vals))
        if i >= maxrows:
            print('... truncated at %d rows' % maxrows)
            break

for sheet in sys.argv[1:] or ['Project Dashboard', 'Escrow Allocation Summary']:
    dump(sheet)
    print()
