#!/bin/bash
DB=sgc_mt_parkgroup
echo "=== ACL entries for every model the dashboard touches ==="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d $DB -c "
SELECT m.model,
       a.name->>'en_US' AS acl_name,
       g.name->>'en_US' AS grp,
       a.perm_read, a.perm_write, a.perm_create, a.perm_unlink
FROM ir_model m
LEFT JOIN ir_model_access a ON a.model_id = m.id
LEFT JOIN res_groups g ON g.id = a.group_id
WHERE m.model IN ('property.details','property.project','sale.contract.installment',
                  'escrow.allocation','sale.contract','escrow.release')
ORDER BY m.model, a.id;"

echo ""
echo "=== models with NO acl row at all (superuser-only) ==="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d $DB -c "
SELECT m.model FROM ir_model m
LEFT JOIN ir_model_access a ON a.model_id = m.id
WHERE m.model IN ('property.details','property.project','sale.contract.installment',
                  'escrow.allocation','sale.contract','escrow.release')
  AND a.id IS NULL;"

echo ""
echo "=== record rules on those models ==="
docker exec -i sgc_rent_mt_db psql -U odoo_mt -d $DB -c "
SELECT m.model, r.name->>'en_US' AS rule, r.domain
FROM ir_rule r JOIN ir_model m ON m.id = r.model_id
WHERE m.model IN ('property.details','property.project','sale.contract.installment',
                  'escrow.allocation','sale.contract','escrow.release')
ORDER BY m.model, r.id;"

echo ""
echo "=== simulate a NON-superuser call as a normal group_user employee ==="
docker exec -i sgc_rent_mt odoo shell -d $DB --no-http <<'PYEOF' 2>&1 | tail -20
env.cr.execute("SELECT id, login FROM res_users ORDER BY id LIMIT 5")
print("users:", env.cr.fetchall())
# pick a non-admin internal user
env.cr.execute("SELECT id, login FROM res_users WHERE id NOT IN (1,2) AND active ORDER BY id")
rows = env.cr.fetchall()
print("candidates:", rows)
import traceback
if rows:
    uid = rows[0][0]
    for model, method in [("property.details","get_development_kpis")]:
        try:
            with env.cr.savepoint():
                env[model].sudo(False)  # no-op marker
                res = env["property.details"].with_user(uid).get_development_kpis()
                keys = sorted(res.keys()) if isinstance(res, dict) else type(res)
                print(f"OK as uid={uid} ({rows[0][1]}): {len(keys)} keys -> {keys[:8]} ...")
                # show a couple of card values
                cards = res.get("cards") or []
                print("cards:", len(cards), "first:", cards[0] if cards else None)
        except Exception as e:
            print(f"FAIL as uid={uid}: {type(e).__name__}: {e}")
            traceback.print_exc()
PYEOF