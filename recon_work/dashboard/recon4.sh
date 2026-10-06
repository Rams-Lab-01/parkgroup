#!/bin/bash
cd /opt/odoo/deploy/sgc-rent-mt
echo "== git =="
git status --short --branch
git remote -v
git log --oneline -6
echo "== docker =="
docker ps --format '{{.Names}} | {{.Image}} | {{.Status}}'
echo "== module states =="
for DB in sgc_mt_parkgroup sgc_mt_template sgc_mt_rectest sgc_mt_esctest; do
  echo "-- $DB"
  docker exec sgc_rent_mt_db psql -U odoo_mt -d "$DB" -At -c "select name||'|'||state||'|'||coalesce(latest_version,'-') from ir_module_module where name like '%offplan%' or name like '%escrow%';" 2>&1
done
echo "== odoo service =="
systemctl list-units --type=service 2>/dev/null | grep -i odoo || echo "no systemd odoo unit"
ps aux | grep -i "[o]doo" | head -5
echo "== config dir =="
ls /opt/odoo/deploy/sgc-rent-mt/config/ 2>/dev/null
echo "== assets purge helper? =="
grep -rn "unlink\|assets_web" /opt/odoo/deploy/sgc-rent-mt/HANDOVER_20261005.md | head -20
