"""Start the server exactly as an MCP client would (python -m vps_mcp over stdio) and use it end to end."""
import json
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

from test_ssh import SHIMS, _settings, vps  # noqa: F401  (fixtures)

ROOT = str(Path(__file__).resolve().parent.parent)


def _env(s, **extra):
    env = {"PATH": f"{SHIMS}:/usr/bin:/bin", "PYTHONPATH": ROOT, "VPS_HOST": s.host, "VPS_PORT": str(s.port),
           "VPS_USER": s.user, "VPS_SSH_KEY": s.key_path, "VPS_KNOWN_HOSTS": s.known_hosts,
           "VPS_DB_NAME": s.db_name, "VPS_DB_CONTAINER": "pg", "VPS_MCP_AUDIT_LOG": s.audit_log}
    env.update(extra)
    return env


async def test_stdio_server_works_end_to_end(vps, tmp_path):  # noqa: F811
    s = _settings(vps, tmp_path)
    transport = StdioTransport(command=sys.executable, args=["-m", "vps_mcp"], env=_env(s), cwd=ROOT)
    async with Client(transport) as c:
        names = {t.name for t in await c.list_tools()}
        assert "docker_ps" in names and "backup_database" not in names
        res = await c.call_tool("docker_ps", {})
        assert "sgc_rent_mt" in res.structured_content["output"]
        blocked = await c.call_tool("sql_readonly", {"query_text": "drop table res_partner"}, raise_on_error=False)
        assert blocked.structured_content["ok"] is False
    assert not any("drop table" in cmd for cmd in vps.commands), "a refused query must never reach the server"
    audit = [json.loads(l) for l in Path(s.audit_log).read_text().splitlines()]
    assert [a["tool"] for a in audit] == ["docker_ps", "sql_readonly"]


async def test_stdio_server_refuses_to_start_with_unsafe_config(vps, tmp_path):  # noqa: F811
    s = _settings(vps, tmp_path)
    Path(s.known_hosts).unlink()
    transport = StdioTransport(command=sys.executable, args=["-m", "vps_mcp"], env=_env(s), cwd=ROOT)
    with pytest.raises(Exception):
        async with Client(transport) as c:
            await c.list_tools()
