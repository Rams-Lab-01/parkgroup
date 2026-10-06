p = 'rental_property_dashboard.js'
s = open(p, encoding='utf-8', errors='replace').read()
lines = s.split('\n')

# strip strings/comments per line-ish, then find unmatched ( and )
stack = []
state = None
i, n = 0, len(s)
line = 1
while i < n:
    c = s[i]
    if c == '\n':
        line += 1
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
        if c == '(':
            stack.append((line, i))
        elif c == ')':
            if stack:
                stack.pop()
            else:
                print('UNMATCHED ) at line', line, '->', lines[line - 1].strip()[:120])
    elif state == 'line':
        if c == '\n':
            state = None
    elif state == 'block':
        if c == '*' and nxt == '/':
            state = None; i += 2; continue
    elif state in ('"', "'", '`'):
        if c == '\\':
            i += 2; continue
        if c == state:
            state = None
    i += 1

for (ln, off) in stack:
    print('UNCLOSED ( opened at line', ln, '->', lines[ln - 1].strip()[:120])
if not stack:
    print('all parens balanced')