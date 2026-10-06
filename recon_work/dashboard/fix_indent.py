p = 'property_details.py'
lines = open(p, encoding='utf-8', errors='replace').read().split('\n')

# 1-indexed file lines 785..800 are wrongly nested inside "if not last_activity_date:"
start, end = 785, 800
for i in range(start - 1, end):
    if lines[i].startswith('    '):
        lines[i] = lines[i][4:]

open(p, 'w', encoding='utf-8', newline='').write('\n'.join(lines))

print('dedented lines %d..%d' % (start, end))
for i in range(start - 3, end + 4):
    print(i, repr(lines[i - 1]))