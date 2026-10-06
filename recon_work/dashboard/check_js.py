import re

p = 'rental_property_dashboard.js'
s = open(p, encoding='utf-8', errors='replace').read()

# 1) no leftover orphan / duplicate registrations
print('registration occurrences:', s.count('dashboardActions.add'))
print('watchlist assignments  :', s.count('this.state.watchlist ='))
print('cards assignments      :', s.count('this.state.cards ='))
print('_buildCards defs       :', s.count('_buildCards(payload)'))

# 2) hardcoded KPI numbers should NOT appear (they must come from payload)
bad = re.findall(r'value:\s*"(?:\d|AED)', s)
print('hardcoded card values  :', len(bad), bad[:5])

# 3) brace / paren / bracket balance ignoring strings & comments
i, n = 0, len(s)
state = None  # None | '"' | "'" | '`' | 'line' | 'block'
depth = {'{': 0, '(': 0, '[': 0}
pairs = {'}': '{', ')': '(', ']': '['}
while i < n:
    c = s[i]
    nxt = s[i + 1] if i + 1 < n else ''
    if state is None:
        if c == '/' and nxt == '/':
            state = 'line'; i += 2; continue
        if c == '/' and nxt == '*':
            state = 'block'; i += 2; continue
        if c in '"\'':
            state = c; i += 1; continue
        if c == '`':
            state = '`'; i += 1; continue
        if c in depth:
            depth[c] += 1
        elif c in pairs:
            depth[pairs[c]] -= 1
    elif state == 'line':
        if c == '\n': state = None
    elif state == 'block':
        if c == '*' and nxt == '/': state = None; i += 2; continue
    elif state in ('"', "'", '`'):
        if c == '\\': i += 2; continue
        if c == state: state = None
    i += 1

print('\nbalance  braces=%d parens=%d brackets=%d' % (depth['{'], depth['('], depth['[']))
print('end state :', state)

# 4) template literal interpolation sanity (backticks balanced)
print('backticks :', s.count('`') % 2 == 0 and 'even' or 'ODD (unbalanced)')

# 5) show the class/registration tail
print('\n--- last 700 chars ---')
print(s[-700:])