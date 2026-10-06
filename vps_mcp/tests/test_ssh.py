"""The real SSH path: an asyncssh server on localhost stands in for the VPS."""
import asyncio
import json
import os
from pathlib import Path

import asyncssh
import pytest
from fastmcp import Client

from vps_mcp.config import Settings
from vps_mcp.executor import ExecError, SSHExecutor
from vps_mcp.server import build_server, check_connection

SHIMS = str(Path(__file__).parent / "shims")


class FakeVPS:
    def __init__(self):
        self.connections = 0
        self.commands: list[str] = []
        self.port = 0
        self.dir: Path | None = None
        self.host_key = None
        self.client_key = None


async def _handle(process, vps: FakeVPS):
    vps.commands.append(process.command)
    stdin = await process.stdin.read()
    proc = await asyncio.create_subprocess_exec(
        "/bin/sh", "-c", process.command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate(stdin)
    try:                       # a client that already gave up (timeout / output cap) must not crash the server
        process.stdout.write(out)
        process.stderr.write(err)
        process.exit(proc.returncode)
    except (BrokenPipeError, ConnectionError, asyncssh.Error, OSError):
        pass


@pytest.fixture
async def vps(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", f"{SHIMS}:{os.environ['PATH']}")
    fake = FakeVPS()
    fake.dir = tmp_path
    fake.host_key = asyncssh.generate_private_key("ssh-ed25519")
    fake.client_key = asyncssh.generate_private_key("ssh-ed25519")
    authorized = tmp_path / "authorized_keys"
    authorized.write_bytes(fake.client_key.export_public_key())

    class Srv(asyncssh.SSHServer):
        def connection_made(self, conn):
            fake.connections += 1

    server = await asyncssh.listen(
        "127.0.0.1", 0, server_factory=Srv, server_host_keys=[fake.host_key], authorized_client_keys=str(authorized),
        process_factory=lambda p: _handle(p, fake), encoding=None)
    fake.port = server.get_port()
    yield fake
    server.close()
    await server.wait_closed()


def _settings(vps: FakeVPS, tmp_path: Path, *, host_key=None, client_key=None, **over) -> Settings:
    key_file = tmp_path / "client_key"
    (client_key or vps.client_key).write_private_key(str(key_file))
    key_file.chmod(0o600)
    known = tmp_path / "known_hosts"
    known.write_text(f"[127.0.0.1]:{vps.port} " + (host_key or vps.host_key).export_public_key().decode())
    base = dict(host="127.0.0.1", port=vps.port, user="deploy", key_path=str(key_file), known_hosts=str(known),
                db_name="it5", db_container="pg", audit_log=str(tmp_path / "audit.jsonl"), command_timeout=20)
    base.update(over)
    return Settings(**base)


async def test_commands_run_over_ssh_with_stdin_and_exit_codes(vps, tmp_path):
    ex = SSHExecutor(_settings(vps, tmp_path))
    try:
        ok = await ex.run("echo out; echo err 1>&2")
        assert ok.ok and ok.stdout.strip() == "out" and ok.stderr.strip() == "err"
        assert (await ex.run("cat", stdin="piped input")).stdout == "piped input"
        failed = await ex.run("exit 3")
        assert failed.exit_status == 3 and not failed.ok
        assert vps.connections == 1, "the connection must be reused"
    finally:
        await ex.close()


async def test_host_key_mismatch_is_refused_and_nothing_runs(vps, tmp_path):
    impostor = asyncssh.generate_private_key("ssh-ed25519")
    ex = SSHExecutor(_settings(vps, tmp_path, host_key=impostor))
    with pytest.raises(ExecError, match="Host key verification FAILED"):
        await ex.run("echo should-not-run")
    assert vps.commands == []


async def test_unlisted_host_is_refused(vps, tmp_path):
    s = _settings(vps, tmp_path)
    Path(s.known_hosts).write_text("")
    with pytest.raises(ExecError):
        await SSHExecutor(s).run("echo nope")
    assert vps.commands == []


async def test_wrong_client_key_is_refused(vps, tmp_path):
    stranger = asyncssh.generate_private_key("ssh-ed25519")
    ex = SSHExecutor(_settings(vps, tmp_path, client_key=stranger))
    with pytest.raises(ExecError, match="authentication refused"):
        await ex.run("echo nope")
    assert vps.commands == []


async def test_unreachable_server_gives_a_clear_error(vps, tmp_path):
    ex = SSHExecutor(_settings(vps, tmp_path, port=1))
    with pytest.raises(ExecError, match="Could not connect"):
        await ex.run("true")


async def test_timeout_and_output_cap_over_ssh(vps, tmp_path):
    ex = SSHExecutor(_settings(vps, tmp_path))
    try:
        slow = await ex.run("sleep 4; echo late", timeout=0.5)
        assert slow.timed_out and "late" not in slow.stdout
        big = await ex.run("yes abcdefghij | head -c 3000000", max_bytes=4000)
        assert big.truncated and len(big.stdout) <= 4000
        assert (await ex.run("echo still-works")).stdout.strip() == "still-works"
    finally:
        await ex.close()


async def test_full_mcp_round_trip_over_ssh(vps, tmp_path):
    s = _settings(vps, tmp_path)
    executor = SSHExecutor(s)
    try:
        async with Client(build_server(s, executor)) as c:
            ps = (await c.call_tool("docker_ps", {})).structured_content
            logs = (await c.call_tool("odoo_logs", {"lines": 5, "grep": "x; id"}, raise_on_error=False)).structured_content
        assert ps["ok"] and "sgc_rent_mt" in ps["output"]
        assert logs["ok"] is not None
        # the dangerous-looking filter reached the server as ONE quoted argument, never as a second command
        sent = [c for c in vps.commands if "grep" in c][0]
        assert "-F -- 'x; id'" in sent
        audit = [json.loads(l) for l in Path(s.audit_log).read_text().splitlines()]
        assert [a["tool"] for a in audit] == ["docker_ps", "odoo_logs"]
    finally:
        await executor.close()


async def test_connection_check_command(vps, tmp_path, capsys):
    s = _settings(vps, tmp_path)
    assert await check_connection(s) == 0
    assert "connected as" in capsys.readouterr().out
    bad = _settings(vps, tmp_path, host_key=asyncssh.generate_private_key("ssh-ed25519"))
    assert await check_connection(bad) == 1
    assert "Host key verification FAILED" in capsys.readouterr().err
