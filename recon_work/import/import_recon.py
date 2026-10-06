# -*- coding: utf-8 -*-
"""Park Group reconciliation import — runs inside `odoo shell`.

Phases: units create -> units update -> buyers -> brokers -> contracts -> installments -> verify.
Idempotent: external ids (module 'parkgroup_recon') + natural keys; safe to re-run.
Dry run: set env IMPORT_DRY=1 to log without writing.
"""
import csv, os, re, sys

BASE = '/tmp/pg_import'
OUT_DIR = '/tmp/pg_import_out'
os.makedirs(OUT_DIR, exist_ok=True)
DRY = os.environ.get('IMPORT_DRY') == '1'
MOD = 'parkgroup_recon'

report = []
def L(msg):
    report.append(str(msg))
    print(str(msg), flush=True)

def rd(name):
    with open(os.path.join(BASE, name), encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def fnum(v):
    s = str(v or '').strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None

def fint(v):
    n = fnum(v)
    return int(n) if n is not None else None

def xid(name):
    return env['ir.model.data'].search([('module', '=', MOD), ('name', '=', name)], limit=1)

def xid_register(name, model, res_id):
    if not xid(name):
        env['ir.model.data'].create({'module': MOD, 'name': name, 'model': model, 'res_id': res_id})

def xid_res_id(name, model):
    x = env['ir.model.data'].search([('module', '=', MOD), ('name', '=', name), ('model', '=', model)], limit=1)
    return x.res_id if x else None

def xname(prefix, key):
    """ir_model_data.name must match ^[a-zA-Z0-9./_]+$"""
    return re.sub(r'[^a-zA-Z0-9./_]', '_', '%s_%s' % (prefix, key))

L('DB=%s user=%s dry_run=%s' % (env.cr.dbname, env.user.id, DRY))
company = env.company
L('company=%s (%s)' % (company.id, company.name))

projects = {p.code: p for p in env['property.project'].search([])}
L('projects: %s' % {k: v.id for k, v in projects.items()})

counts = {}

# ---------------- PHASE 1: create units ----------------
creates = rd('units_create.csv')
c_new = c_skip = 0
for row in creates:
    x = xid(row['external_id'])
    if x:
        c_skip += 1
        continue
    proj = projects.get(row['project_code'])
    if not proj:
        L('!! unit create: unknown project %s' % row['project_code'])
        continue
    existing = env['property.details'].search(
        [('project_id', '=', proj.id), ('unit_number', '=', row['unit_number'])], limit=1)
    if existing:
        xid_register(row['external_id'], 'property.details', existing.id)
        c_skip += 1
        continue
    vals = {
        'name': row['name'], 'property_code': row['property_code'],
        'project_id': proj.id, 'unit_number': row['unit_number'],
        'state': row['state'], 'property_type': row['property_type'],
        'sale_lease': row['sale_lease'], 'company_id': company.id,
    }
    f = fint(row.get('floor'))
    if f is not None: vals['floor'] = f
    if row.get('unit_type'): vals['unit_type'] = row['unit_type']
    for src, dst in [('area', 'area'), ('price', 'price'), ('sale_price', 'sale_price'),
                     ('admin_fee', 'admin_fee')]:
        v = fnum(row.get(src))
        if v is not None: vals[dst] = v
    if DRY:
        c_new += 1
        continue
    unit = env['property.details'].create(vals)
    xid_register(row['external_id'], 'property.details', unit.id)
    c_new += 1
counts['units_created'] = c_new; counts['units_create_skipped'] = c_skip
L('phase1 units: created=%d skipped=%d' % (c_new, c_skip))
if not DRY: env.cr.commit()

# ---------------- PHASE 2: update units ----------------
updates = rd('units_update.csv')
u_upd = u_skip = u_hold = 0
for row in updates:
    uid = fint(row['odoo_id'])
    unit = env['property.details'].browse(uid)
    if not unit.exists():
        L('!! unit update: missing id %s (%s/%s)' % (row['odoo_id'], row['project_code'], row['unit_number']))
        continue
    vals = {}
    if row.get('name'): vals['name'] = row['name']
    for src, dst in [('price', 'price'), ('sale_price', 'sale_price'), ('area', 'area'),
                     ('admin_fee', 'admin_fee')]:
        v = fnum(row.get(src))
        if v is not None: vals[dst] = v
    if row.get('unit_type'): vals['unit_type'] = row['unit_type']
    st = (row.get('state') or '').strip()
    if st == 'HOLD':
        u_hold += 1
        L('HOLD state for %s/%s (blocked row, no change applied)' % (row['project_code'], row['unit_number']))
    elif st in ('sold', 'available'):
        vals['state'] = st
    if not vals:
        u_skip += 1
        continue
    if DRY:
        u_upd += 1
        continue
    unit.write(vals)
    u_upd += 1
counts['units_updated'] = u_upd; counts['units_update_skipped'] = u_skip; counts['state_held'] = u_hold
L('phase2 units update: updated=%d skipped=%d held=%d' % (u_upd, u_skip, u_hold))
if not DRY: env.cr.commit()

# ---------------- PHASE 3: buyers ----------------
buyers = rd('buyers.csv')
buyer_map = {}
b_new = b_match = 0
for row in buyers:
    key = row['buyer_key']
    rid = xid_res_id(xname('buyer', key), 'res.partner')
    partner = env['res.partner'].browse(rid) if rid else env['res.partner']
    if not partner:
        email = (row.get('email') or '').strip()
        name = (row.get('name') or '').strip()
        if email:
            partner = env['res.partner'].search([('email', '=ilike', email)], limit=1)
        if not partner and name:
            partner = env['res.partner'].search([('name', '=ilike', name)], limit=1)
    if partner:
        b_match += 1
    else:
        if DRY:
            partner = env['res.partner'].browse(0)
        else:
            partner = env['res.partner'].create({
                'name': row['name'], 'email': row['email'] or False,
                'phone': row['mobile'] or False,
                'user_type': 'customer', 'is_sold_customer': True,
            })
        b_new += 1
    if partner.id:
        buyer_map[key] = partner.id
        if not DRY:
            xid_register(xname('buyer', key),
                         'res.partner', partner.id)
counts['buyers_created'] = b_new; counts['buyers_matched'] = b_match
L('phase3 buyers: created=%d matched=%d mapped=%d' % (b_new, b_match, len(buyer_map)))
if not DRY: env.cr.commit()

# ---------------- PHASE 4: brokers ----------------
brokers = rd('brokers.csv')
broker_map = {}
k_new = k_match = 0
for row in brokers:
    key = row['broker_key']
    rid = xid_res_id(xname('broker', key), 'res.partner')
    partner = env['res.partner'].browse(rid) if rid else env['res.partner']
    if not partner:
        partner = env['res.partner'].search([('name', '=ilike', row['name'])], limit=1)
    if partner:
        k_match += 1
    else:
        if DRY:
            partner = env['res.partner'].browse(0)
        else:
            partner = env['res.partner'].create({
                'name': row['name'], 'is_company': True, 'user_type': 'broker',
            })
            xid_register(xname('broker', key),
                         'res.partner', partner.id)
            if row.get('contact_name'):
                contact = env['res.partner'].create({
                    'name': row['contact_name'], 'parent_id': partner.id, 'is_company': False,
                    'email': row.get('contact_email') or False, 'phone': row.get('contact_mobile') or False,
                })
                xid_register(xname('broker_contact', key),
                              'res.partner', contact.id)
        k_new += 1
    if partner.id:
        broker_map[key] = partner.id
counts['brokers_created'] = k_new; counts['brokers_matched'] = k_match
L('phase4 brokers: created=%d matched=%d mapped=%d' % (k_new, k_match, len(broker_map)))
if not DRY: env.cr.commit()

# ---------------- PHASE 5: contracts ----------------
contracts = rd('contracts.csv')

def find_unit(proj_code, unit_number, unit_key=''):
    proj = projects.get(proj_code)
    if not proj:
        return None
    for val in dict.fromkeys([(unit_number or '').strip(), (unit_key or '').strip()]):
        if val:
            rec = env['property.details'].search(
                [('project_id', '=', proj.id), ('unit_number', '=', val)], limit=1)
            if rec:
                return rec
    return False

ct_new = ct_skip = 0
contract_map = {}
missing = []
for row in contracts:
    key = row['contract_key']
    rid = xid_res_id('contract_%s' % key, 'sale.contract')
    contract = env['sale.contract'].browse(rid) if rid else env['sale.contract']
    if not contract:
        unit = find_unit(row['project_code'], row['unit_number'], row.get('unit_key', ''))
        if not unit:
            missing.append('unit %s/%s' % (row['project_code'], row['unit_number']))
            continue
        buyer_id = buyer_map.get(row['buyer_key'])
        if not buyer_id:
            missing.append('buyer %s (%s/%s)' % (row['buyer_key'], row['project_code'], row['unit_number']))
            continue
        contract = env['sale.contract'].search(
            [('property_id', '=', unit.id), ('buyer_id', '=', buyer_id)], limit=1)
    if contract:
        ct_skip += 1
    else:
        unit = find_unit(row['project_code'], row['unit_number'], row.get('unit_key', ''))
        buyer_id = buyer_map.get(row['buyer_key'])
        vals = {
            'property_id': unit.id, 'buyer_id': buyer_id,
            'sale_price': fnum(row['sale_price']) or 0.0,
            'state': 'signed', 'company_id': company.id,
            'notes': 'Imported from reconciled sales workbook (parkgroup_recon)',
        }
        cd = (row.get('contract_date') or '').strip()
        if cd:
            vals['contract_date'] = cd
        ba = fnum(row.get('booking_amount'))
        if ba:
            vals['booking_amount'] = ba
        if DRY:
            contract = env['sale.contract'].browse(0)
        else:
            contract = env['sale.contract'].create(vals)
        ct_new += 1
    if contract.id:
        contract_map[key] = contract.id
        if not DRY:
            xid_register('contract_%s' % key, 'sale.contract', contract.id)
counts['contracts_created'] = ct_new; counts['contracts_skipped'] = ct_skip
L('phase5 contracts: in_csv=%d created=%d skipped=%d mapped=%d' % (len(contracts), ct_new, ct_skip, len(contract_map)))
for m in missing[:20]:
    L('!! contract skipped: %s' % m)
if not DRY: env.cr.commit()

# ---------------- PHASE 6: installments ----------------
installments = rd('installments.csv')
ln_new = ln_skip = ln_paid = 0
for row in installments:
    cid = contract_map.get(row['contract_key'])
    if not cid:
        continue
    existing = env['sale.contract.installment'].search(
        [('contract_id', '=', cid), ('name', '=', row['name'])], limit=1)
    if existing:
        ln_skip += 1
        continue
    vals = {
        'contract_id': cid, 'name': row['name'], 'sequence': fint(row['sequence']) or 1,
        'amount': fnum(row['amount']) or 0.0, 'percentage': fnum(row['percentage']) or 0.0,
        'notes': row.get('notes') or False,
    }
    if row.get('due_date'): vals['due_date'] = row['due_date']
    if row.get('payment_date'): vals['payment_date'] = row['payment_date']
    if DRY:
        ln_new += 1
        continue
    line = env['sale.contract.installment'].create(vals)
    if (row.get('state') or '') == 'paid':
        line.write({'state': 'paid'})
        ln_paid += 1
    ln_new += 1
counts['installments_created'] = ln_new; counts['installments_skipped'] = ln_skip
L('phase6 installments: in_csv=%d created=%d skipped=%d marked_paid=%d' % (len(installments), ln_new, ln_skip, ln_paid))
if not DRY: env.cr.commit()

# ---------------- PHASE 7: verify ----------------
if not DRY:
    env.flush_all()
    all_contracts = env['sale.contract'].browse(list(contract_map.values()))
    # force recompute of total_paid (dependency cascade safeguard)
    all_contracts._compute_total_paid()
    env.flush_all()
    n_units = env['property.details'].search_count([])
    n_sold_units = env['property.details'].search_count([('state', '=', 'sold')])
    n_contracts = env['sale.contract'].search_count([])
    n_inst = env['sale.contract.installment'].search_count([])
    n_inst_paid = env['sale.contract.installment'].search_count([('state', '=', 'paid')])
    n_customers = env['res.partner'].search_count([('user_type', '=', 'customer')])
    n_brokers = env['res.partner'].search_count([('user_type', '=', 'broker')])
    L('VERIFY units=%d sold=%d contracts=%d installments=%d paid=%d customers=%d brokers=%d' %
      (n_units, n_sold_units, n_contracts, n_inst, n_inst_paid, n_customers, n_brokers))
    # sample contract check
    for key in list(contract_map)[:3]:
        c = env['sale.contract'].browse(contract_map[key])
        L('SAMPLE %s: %s | %s | price=%s | paid=%s | installments=%d' %
          (key, c.name, c.buyer_id.name, c.sale_price, c.total_paid, len(c.installment_ids)))

with open(os.path.join(OUT_DIR, 'import_report.csv'), 'w', encoding='utf-8') as f:
    f.write('metric,value\n')
    for k, v in counts.items():
        f.write('%s,%s\n' % (k, v))
print('REPORT_SAVED', os.path.join(OUT_DIR, 'import_report.csv'), flush=True)
if not DRY: env.cr.commit()
print('IMPORT_DONE', flush=True)
