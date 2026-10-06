tot = env['ir.asset'].sudo().search_count([])
print('ir.asset total records = %d' % tot)

samples = env['ir.asset'].sudo().search([], limit=5)
for a in samples:
    print('  sample: bundle=%r path=%r' % (a.bundle, a.path))

print('')
print('--- all IrAsset methods ---')
for m in sorted(dir(env['ir.asset'])):
    if not m.startswith('__'):
        print('   ' + m)

print('')
print('--- look for bundle generation helpers elsewhere ---')
import odoo.addons.base.models.ir_asset as ia
print('  module funcs: %s' % [f for f in dir(ia) if not f.startswith('_')])

env.cr.rollback()
print('')
print('DONE (rolled back)')