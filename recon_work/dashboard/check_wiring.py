import re

tpl = open('template.xml', encoding='utf-8', errors='replace').read()
js = open('rental_property_dashboard.js', encoding='utf-8', errors='replace').read()

refs = sorted(set(re.findall(r't-ref="([^"]+)"', tpl)))
print('t-ref in template :', refs)
use_refs = sorted(set(re.findall(r'useRef\("([^"]+)"\)', js)))
print('useRef in JS      :', use_refs)
missing_refs = [r for r in refs if r not in use_refs]
print('MISSING REFS      :', missing_refs or 'none')

handlers = sorted(set(re.findall(r't-on-click="([A-Za-z_][A-Za-z0-9_]*)', tpl)))
print('\nclick handlers    :', handlers)
methods = set(re.findall(r'^\s{4}([A-Za-z_][A-Za-z0-9_]*)\s*\(', js, re.M))
methods |= set(re.findall(r'^\s{4}(?:async\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(', js, re.M))
methods |= set(re.findall(r'get\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(', js))
print('MISSING METHODS   :', [h for h in handlers if h not in methods] or 'none')

# formatXxx helpers used with t-esc
fmt = sorted(set(re.findall(r't-esc="(format[A-Za-z]+)\(', tpl)))
print('\nformat helpers    :', fmt)
missing_fmt = [f for f in fmt if f + '(' not in js]
print('MISSING FORMATTERS:', missing_fmt or 'none')

# dynamic handler this[card.action]()
print('\ndynamic this[card.action]() present:', 'this[card.action]()' in tpl)
print('state.cards defined in JS         :', 'this.state.cards = this._buildCards(payload)' in js)
print('project_rows defined in JS        :', 'this.state.project_rows' in js)
print('aging_undated used in template    :', 'state.aging_undated' in tpl)