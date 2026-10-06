"""Verify the MCP server exposes its tools/resources over the real MCP protocol.

Runs a genuine stdio MCP client handshake against ``server.py`` and lists every
advertised tool.  No Odoo credentials and no network access are required -
tool discovery must not authenticate.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


async def main() -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    # Poison the environment: if anything tries to authenticate during
    # discovery or tool listing, it will fail loudly instead of silently
    # reaching the real Odoo instance.
    env = {
        **os.environ,
        "PGRE_URL": "http://127.0.0.1:1",
        "PGRE_DB": "nonexistent",
        "PGRE_KEY": "not-a-real-key",
        "PGRE_LOGIN": "nobody@example.invalid",
        "PYTHONPATH": str(HERE),
    }

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "server"],
        env=env,
        cwd=str(HERE),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"protocol : {init.protocolVersion}")
            print(f"server   : {init.serverInfo.name} v{init.serverInfo.version}")
            print()

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f"TOOLS ({len(names)}):")
            for tool in sorted(tools.tools, key=lambda t: t.name):
                required = ",".join(tool.inputSchema.get("required", []) or []) or "-"
                summary = (tool.description or "").strip().splitlines()[0][:70]
                print(f"  - {tool.name}")
                print(f"      {summary}")
                print(f"      required: {required}")
            print()

            resources = await session.list_resources()
            res_names = [str(getattr(r, "uri", r)) for r in resources.resources]
            print(f"RESOURCES ({len(res_names)}): {res_names}")

            expected = {
                "odoo_whoami", "list_financial_buckets", "get_invoices",
                "get_payments", "get_journal_entries", "get_move_lines",
                "list_journals", "list_partners", "financial_summary", "find_unpaid",
            }
            missing = expected - set(names)
            if missing:
                print(f"\nFAIL: missing tools: {sorted(missing)}")
                return 1
            if not any("buckets" in r for r in res_names):
                print("\nFAIL: the odoo://buckets resource is not advertised")
                return 1

            # A tool call must fail gracefully with guidance, not a traceback.
            print("\nCalling odoo_whoami with poisoned credentials (expect a clean error):")
            result = await session.call_tool("odoo_whoami", {})
            text = " ".join(
                getattr(c, "text", "") for c in result.content
            )
            flat = " ".join(text.split())
            print(f"  isError={result.isError}")
            print(f"  message={flat[:220]}")
            if "PGRE_KEY" not in text and "API key" not in text:
                print("\nFAIL: error message does not mention PGRE_KEY / API key")
                return 1

            print("\nRESULT: PASS - MCP handshake, tools, resources and error path all OK")
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))