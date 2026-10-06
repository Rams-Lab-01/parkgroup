import re
p = 'property_details.py'
s = open(p, encoding='utf-8', errors='replace').read()
lines = s.split('\n')

for i, l in enumerate(lines, 1):
    if 'installment' in l or 'sale.contract.installment' in l:
        if 704 <= i <= 790:
            print(i, l)