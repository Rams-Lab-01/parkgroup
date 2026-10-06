#!/bin/bash
echo "=== Cmd/Entrypoint ==="
docker inspect sgc_rent_mt --format '{{json .Config.Cmd}}'
docker inspect sgc_rent_mt --format '{{json .Config.Entrypoint}}'
echo "=== ports ==="
docker port sgc_rent_mt
echo "=== env ==="
docker inspect sgc_rent_mt --format '{{range .Config.Env}}{{println .}}{{end}}' | grep -iE 'db|addons|conf|DATA' | head -12
echo "=== odoo.conf ==="
cat /opt/odoo/deploy/sgc-rent-mt/config/odoo.conf
echo "=== compose files ==="
ls /opt/odoo/deploy/sgc-rent-mt/docker/ 2>/dev/null
find /opt/odoo/deploy/sgc-rent-mt -maxdepth 2 -name 'docker-compose*' -not -name '*.reference-only' 2>/dev/null
echo "=== mounts ==="
docker inspect sgc_rent_mt --format '{{range .Mounts}}{{println .Source " -> " .Destination}}{{end}}'
