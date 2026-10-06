import re

js = open('rental_property_dashboard.js', encoding='utf-8', errors='replace').read()
tpl = open('template.xml', encoding='utf-8', errors='replace').read()
css = open('rental_property_dashboard.css', encoding='utf-8', errors='replace').read()
py = open('property_details.py', encoding='utf-8', errors='replace').read()


def balanced(s):
    stack, pairs = [], {')': '(', ']': '[', '}': '{'}
    instr = None
    i = 0
    while i < len(s):
        c = s[i]
        if instr:
            if c == '\\':
                i += 2
                continue
            if c == instr:
                instr = None
        else:
            if c in '"\'`':
                instr = c
            elif c in '([{':
                stack.append(c)
            elif c in ')]}':
                if not stack or stack[-1] != pairs[c]:
                    return False, 'unbalanced at %d: %r' % (i, c)
                stack.pop()
        i += 1
    return (not stack), ('%d unclosed' % len(stack)) if stack else 'ok'


ok, msg = balanced(js)
print('=== JS bracket balance ===')
print('  %s (%s)' % ('BALANCED' if ok else '*** BROKEN ***', msg))

print('')
print('=== template handlers resolve to methods ===')
handlers = sorted(set(re.findall(r't-on-click="([A-Za-z_][A-Za-z0-9_]*)', tpl)))
defined = set(re.findall(r'^\s{4}([A-Za-z_][A-Za-z0-9_]*)\s*\(', js, re.M))
missing = [h for h in handlers if h not in defined and h != 'this']
print('  handlers: %s' % ', '.join(handlers))
print('  MISSING : %s' % (missing or 'none'))

print('')
print('=== every card action resolves to a view* method ===')
cards = re.findall(r'action:"([A-Za-z_]+)"', js)
uniq = sorted(set(cards))
nomethod = [a for a in uniq if (a + '(') not in js]
print('  distinct actions (%d): %s' % (len(uniq), ', '.join(uniq)))
print('  actions with NO method: %s' % (nomethod or 'none'))

print('')
print('=== all drill-down methods and their domains ===')
for m in re.finditer(r'(view[A-Za-z]+)\(\)\{this\.open\("([a-z_.]+)","([^"]+)",(.*?)\);\}', js):
    name, model, title, dom = m.groups()
    print('  %-20s %-20s %-24s %s' % (name, model, title, dom))

print('')
print('=== card -> action mapping (final) ===')
for m in re.finditer(r'\{label:"([^"]+)",.*?action:"([A-Za-z_]+)"\}', js):
    print('  %-22s -> %s' % (m.group(1), m.group(2)))

print('')
print('=== SIGN CONVENTION CONSISTENCY (server vs client) ===')
srv = re.search(r'under_allocated_count\s*=\s*len\(\[rec for rec in escrow_records if \(rec\.variance_amount or 0\.0\)\s*([<>=]+)\s*(-?[\d.]+)\]\)', py)
srv2 = re.search(r'over_allocated_count\s*=\s*len\(\[rec for rec in escrow_records if \(rec\.variance_amount or 0\.0\)\s*([<>=]+)\s*(-?[\d.]+)\]\)', py)
print('  server under = variance %s %s' % (srv.group(1), srv.group(2)) if srv else '  server under: NOT FOUND')
print('  server over  = variance %s %s' % (srv2.group(1), srv2.group(2)) if srv2 else '  server over: NOT FOUND')
for m in re.finditer(r'viewUnderAllocated\(\)\{this\.open\([^,]+,[^,]+,(\[\[[^\]]+\]\])\)', js):
    print('  client under = %s' % m.group(1))
for m in re.finditer(r'viewOverAllocated\(\)\{this\.open\([^,]+,[^,]+,(\[\[[^\]]+\]\])\)', js):
    print('  client over  = %s' % m.group(1))
for m in re.finditer(r'label:"Under-allocated",count:[^,]+,domain:(\[\[[^\]]+\]\])', js):
    print('  watch under  = %s' % m.group(1))
for m in re.finditer(r'label:"Over-allocated",count:[^,]+,domain:(\[\[[^\]]+\]\])', js):
    print('  watch over   = %s' % m.group(1))

consistent = (srv and srv.group(1) == '<' and srv2 and srv2.group(1) == '>'
              and 'viewUnderAllocated(){this.open("escrow.allocation","Under-Allocated",[["variance_amount","<",-0.01]])' in js
              and 'viewOverAllocated(){this.open("escrow.allocation","Over-Allocated",[["variance_amount",">",0.01]])' in js)
print('  ALL FOUR AGREE ON SIGN: %s' % ('YES' if consistent else '*** NO ***'))

print('')
print('=== hardcode / placeholder audit ===')
for w in ['TODO', 'FIXME', 'Lorem ipsum', 'DUMMY', 'SAMPLE_DATA']:
    print('  %-12s JS=%d  PY=%d' % (w, len(re.findall(w, js, re.I)), len(re.findall(w, py, re.I))))
print('  dashboardActions.add count = %d' % js.count('dashboardActions.add('))
print('  this.state.cards assign    = %d' % js.count('this.state.cards ='))
print('  hardcoded count:0 watchlist = %d' % len(re.findall(r'label:"[^"]*",count:0,', js)))