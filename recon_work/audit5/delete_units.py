# -*- coding: utf-8 -*-
"""Delete RES/103, RES/104, RES/204 (property_details 827/828/832) - client-confirmed 2026-10-05:
units not present in source inventory (Consolidated_Sales_Workbook (4).xlsx).
Deletion is Tier-1 audited by sgc_offplan_rental_property_management: operator reasons are
registered via SgcAuditInternalService before unlink (same path as the UI 'Delete with audit reason').
Full-row backup: /opt/parkgroup-recon/units_deleted_827_828_832_20261005.csv
Run: docker exec -i sgc_rent_mt /entrypoint.sh odoo shell -d sgc_mt_parkgroup --no-http --log-level=warn < delete_units.py
"""
import os
report = []
def L(m):
    s = str(m); report.append(s); print(s, flush=True)

from odoo.addons.sgc_offplan_rental_property_management.services import sgc_audit_internal_service
svc = sgc_audit_internal_service.SgcAuditInternalService(env)

expected = {827: '103', 828: '104', 832: '204'}
recs = env['property.details'].browse(list(expected))
ex = recs.exists()
L('found: %s' % sorted(ex.ids))
for r in ex:
    L('id=%s unit_number=%r state=%s project=%s' % (r.id, r.unit_number, r.state, r.project_id))
    if str(r.unit_number).strip() != expected[r.id]:
        L('!! unit number mismatch for id %s - ABORT' % r.id)
        raise SystemExit(1)

reason = ('Client-confirmed 2026-10-05: unit not present in approved source inventory '
          '(Consolidated_Sales_Workbook (4).xlsx); no contract, collection or document attached; '
          'full-row backup at /opt/parkgroup-recon/units_deleted_827_828_832_20261005.csv')
for r in ex:
    entry = svc.register_reason('property.details', r.id, reason)
    L('reason registered for %s (correlation=%s)' % (r.id, entry['correlation_uuid'][:12]))

L('unlinking %d records' % len(ex))
ex.unlink()
env.cr.commit()

env.cr.execute("select count(*) from property_details")
L('total property_details remaining: %s' % env.cr.fetchone()[0])
env.cr.execute("select pr.code, count(*) from property_details d join property_project pr on pr.id=d.project_id group by 1 order by 1")
L('by project: %s' % env.cr.fetchall())
env.cr.execute("select count(*) from property_details d where d.state='sold'")
L('sold state remaining: %s' % env.cr.fetchone()[0])

os.makedirs('/tmp/pg_state', exist_ok=True)
open('/tmp/pg_state/delete_units_827_828_832_report.txt', 'w').write('\n'.join(report) + '\n')
L('DELETE_DONE')
