import re

p = 'property_project_views.xml'
s = open(p, encoding='utf-8', errors='replace').read()

t = '<field name="zip"/>'
print('zip occurrences:', s.count(t))
for m in re.finditer(re.escape(t), s):
    print('  at line', s[:m.start()].count('\n') + 1)

# find all Location groups
for m in re.finditer(r'<group string="Location">', s):
    ln = s[:m.start()].count('\n') + 1
    end = s.find('</group>', m.start())
    print('--- Location group at line', ln, '---')
    print(s[m.start():end + 8])
    print()