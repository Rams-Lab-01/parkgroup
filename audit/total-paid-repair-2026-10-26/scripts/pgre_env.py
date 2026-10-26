import os, sys
sys.path.insert(0, r"C:\Parkgroup Data\odoo_mcp")
for line in open(r"C:\Parkgroup Data\odoo_mcp\.env", encoding="utf-8"):
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.strip().split("=", 1)
        os.environ.setdefault(k, v.strip().strip('"'))
from pgre_client import OdooClient
c = OdooClient()
