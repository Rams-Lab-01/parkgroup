qweb = env['ir.qweb'].sudo()

print('=== structure probe ===')
b = qweb._get_asset_bundle('web.assets_backend', css=True, js=True)
print('  _get_asset_bundle type = %s' % type(b).__name__)
print('  repr = %r' % (b,))

print('')
print('=== _get_asset_content (real content) ===')
try:
    c = qweb._get_asset_content('web.assets_backend')
    print('  type = %s' % type(c).__name__)
    if isinstance(c, dict):
        print('  keys = %s' % list(c.keys()))
        for k, v in c.items():
            print('    %-10s %s len=%s' % (k, type(v).__name__, len(v) if hasattr(v, '__len__') else 'n/a'))
    elif isinstance(c, (list, tuple)):
        print('  len = %d' % len(c))
        print('  first item type = %s' % type(c[0]).__name__)
except Exception as e:
    print('  ERROR: %s: %s' % (type(e).__name__, e))

env.cr.rollback()
print('')
print('DONE (rolled back)')