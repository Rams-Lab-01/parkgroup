qweb = env['ir.qweb'].sudo()

b = qweb._get_asset_bundle('web.assets_backend', css=True, js=True)
print('=== AssetsBundle public methods ===')
for m in sorted(dir(b)):
    if not m.startswith('__'):
        print('   ' + m)

print('')
print('=== bundle internals ===')
for attr in ('bundle_name', 'name', 'direction', 'assets_count', 'lines', 'css', 'js'):
    if hasattr(b, attr):
        v = getattr(b, attr)
        try:
            n = len(v)
        except Exception:
            n = ''
        print('   %-14s = %s (len=%s)' % (attr, str(v)[:80], n))

print('')
print('=== try likely content accessors ===')
for meth in ('js_content', 'css_content', 'get_content', '_get_content', 'content', 'urls', 'js_urls', 'css_urls', 'generate'):
    if hasattr(b, meth):
        try:
            out = getattr(b, meth)()
            t = out if isinstance(out, str) else ('\n'.join(out) if isinstance(out, (list, tuple)) else str(out))
            print('   %-14s -> %s len=%d' % (meth, type(out).__name__, len(t)))
        except Exception as e:
            print('   %-14s -> ERROR %s' % (meth, e))

env.cr.rollback()
print('')
print('DONE (rolled back)')