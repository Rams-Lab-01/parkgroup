#!/bin/sh
B=/var/lib/odoo/filestore/sgc_mt_parkgroup/7b/7b81de1be7a5b8c7bf1809a6d1d682ac69dd7573

echo "=== bundle popup line (encoding check) ==="
grep -o 'sgc-popup__count.\{0,150\}' "$B" | head -2

echo ""
echo "=== is the legacy broken domain in the bundle, and in whose code? ==="
if grep -qF '["required_amount",">",["allocated_amount","!=",false]]' "$B"; then
  echo "  legacy pattern present -> extracting context"
  grep -o '.\{300\}\["required_amount",">",\["allocated_amount","!=",false\]\].\{80\}' "$B" | head -1
else
  echo "  legacy pattern ABSENT from bundle (good)"
fi

echo ""
echo "=== all variance_amount domains in the bundle ==="
grep -o '\[\["[a-z_]*","[<>=\[]*",[^]]*\]\]' "$B" | grep variance_amount | sort -u