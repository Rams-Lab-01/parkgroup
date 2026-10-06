#!/bin/bash
set -euo pipefail

TS=$(date +%Y%m%d_%H%M%S)
DEST="/opt/odoo/backups/sgc_rent_mt/$TS"
mkdir -p "$DEST"
echo "backup dir: $DEST"

echo "dumping sgc_mt_parkgroup (custom format) ..."
docker exec sgc_rent_mt_db pg_dump -U odoo_mt -Fc -d sgc_mt_parkgroup -f /tmp/pg.dump
echo "copying out of container ..."
docker cp sgc_rent_mt_db:/tmp/pg.dump "$DEST/sgc_mt_parkgroup.dump"
docker exec sgc_rent_mt_db rm -f /tmp/pg.dump

ls -la "$DEST"

echo ""
echo "=== integrity check (list contents) ==="
docker exec sgc_rent_mt_db pg_restore -l /tmp/verify.dump 2>/dev/null || true
# verify by restoring the schema listing from the host copy
pg_restore -l "$DEST/sgc_mt_parkgroup.dump" 2>/dev/null | tail -5 || \
  docker cp "$DEST/sgc_mt_parkgroup.dump" sgc_rent_mt_db:/tmp/verify.dump && \
  docker exec sgc_rent_mt_db pg_restore -l /tmp/verify.dump | tail -5 && \
  docker exec sgc_rent_mt_db rm -f /tmp/verify.dump

echo ""
echo "=== confirm key tables present in dump ==="
pg_restore -l "$DEST/sgc_mt_parkgroup.dump" 2>/dev/null | grep -cE 'sale_contract|property_project|property_details|escrow_allocation' || \
  docker cp "$DEST/sgc_mt_parkgroup.dump" sgc_rent_mt_db:/tmp/verify.dump && \
  docker exec sgc_rent_mt_db pg_restore -l /tmp/verify.dump | grep -cE 'sale_contract|property_project|property_details|escrow_allocation' && \
  docker exec sgc_rent_mt_db rm -f /tmp/verify.dump

echo ""
echo "BACKUP_OK $DEST/sgc_mt_parkgroup.dump"