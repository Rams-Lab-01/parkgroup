import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest
from fastmcp import Client

from vps_mcp.executor import LocalExecutor
from vps_mcp.server import PG_OPTIONS, build_server
from conftest import PG_DB, needs_postgres

ALL_WRITES = frozenset({"backup_database", "deploy_pull", "odoo_module_command", "odoo_restart"})


async def call(server, name, **args):
    async with Client(server) as c:
        result = await c.call_tool(name, args, raise_on_error=False)
        return result.structured_content or json.loads(result.content[0].text)


def calls_made(env):
    path = Path(env["FAKE_DOCKER_CALLS"])
    return path.read_text().splitlines() if path.exists() else []


# ------------------------------------------------------------------ tool surface
async def test_default_server_exposes_only_read_only_tools(local_server):
    _, server = local_server()
    async with Client(server) as c:
        tools = {t.name: t for t in await c.list_tools()}
    assert set(tools) == {"vps_status", "docker_ps", "odoo_logs", "odoo_modules", "odoo_cron_status",
                          "odoo_mail_queue", "odoo_http_health", "list_databases", "sql_readonly",
                          "deploy_status", "list_backups"}
    assert not (set(tools) & ALL_WRITES), "write tools must not even be visible unless enabled"


async def test_there_is_no_generic_shell_tool(local_server):
    _, server = local_server(enabled_write_tools=ALL_WRITES)
    async with Client(server) as c:
        names = {t.name for t in await c.list_tools()}
    assert not {n for n in names if re.search(r"shell|exec|command$|run_|ssh|bash", n) and n != "odoo_module_command"}


# ------------------------------------------------------------------ read-only tools
async def test_status_and_containers(local_server):
    _, server = local_server()
    status = await call(server, "vps_status")
    assert status["ok"] and "memory" in status["output"] and "Docker version" in status["output"]
    ps = await call(server, "docker_ps")
    assert "sgc_rent_mt" in ps["output"]


async def test_logs_are_filtered_clamped_and_redacted(local_server):
    _, server = local_server()
    res = await call(server, "odoo_logs", lines=3)
    assert res["ok"] and len(res["output"].splitlines()) <= 3
    full = await call(server, "odoo_logs", lines=100)
    assert "hunter2" not in full["output"] and "SuperSecret" not in full["output"]
    assert "[redacted]" in full["output"]
    filtered = await call(server, "odoo_logs", lines=100, grep="ERROR")
    assert filtered["output"].count("\n") == 0 and "something failed" in filtered["output"]
    nothing = await call(server, "odoo_logs", grep="$(touch /tmp/pwned_by_mcp)")
    assert not os.path.exists("/tmp/pwned_by_mcp") and nothing["ok"] is not None
    bad = await call(server, "odoo_logs", since="1h; ls")
    assert bad["ok"] is False and "since" in bad["error"]


@needs_postgres
async def test_database_reads(local_server):
    _, server = local_server()
    mods = await call(server, "odoo_modules", like="sgc%")
    assert mods["ok"] and "sgc_pdc_management" in mods["output"] and mods["row_count"] >= 2
    assert (await call(server, "odoo_cron_status"))["row_count"] > 0
    assert (await call(server, "odoo_mail_queue"))["ok"]
    dbs = await call(server, "list_databases")
    assert dbs["ok"] and PG_DB in dbs["output"]
    inj = await call(server, "odoo_modules", like="x'; drop table res_partner; --")
    assert inj["ok"] is False


@needs_postgres
async def test_sql_readonly_runs_and_limits_rows(local_server, env):
    _, server = local_server()
    res = await call(server, "sql_readonly", query_text="select generate_series(1, 1000) as n", limit=5)
    assert res["ok"] and res["row_count"] == 5 and res["output"].splitlines()[0] == "n"
    err = await call(server, "sql_readonly", query_text="select * from table_that_does_not_exist")
    assert err["ok"] is False and "does not exist" in err["error"]
    assert (await call(server, "sql_readonly", query_text="select 1; select 2"))["ok"] is False
    before = len(calls_made(env))
    refused = await call(server, "sql_readonly", query_text="select password from res_users")
    assert refused["ok"] is False and len(calls_made(env)) == before, "a refused query must never reach the server"
    other_db = await call(server, "sql_readonly", query_text="select 1", db="postgres")
    assert other_db["ok"] is False and "not allowed" in other_db["error"]


@needs_postgres
def test_database_session_itself_is_read_only_even_if_the_guard_were_bypassed(env):
    """Defence in depth: the PGOPTIONS the server always sets make PostgreSQL refuse writes."""
    for statement in ("create table mcp_should_not_exist(x int)", "update res_partner set name = name",
                      "delete from ir_cron", "insert into res_partner(name) values ('x')"):
        cmd = ["docker", "exec", "-i", "-e", f"PGOPTIONS={PG_OPTIONS}", "pg", "psql", "-U", "odoo", "-d", PG_DB,
               "-X", "-A", "-v", "ON_ERROR_STOP=1", "-f", "-"]
        r = subprocess.run(cmd, input=statement, capture_output=True, text=True, env=env)
        assert r.returncode != 0 and "read-only transaction" in r.stderr, statement


async def test_deploy_status_and_backups(local_server, worktree):
    s, server = local_server()
    res = await call(server, "deploy_status")
    assert res["ok"] and "first" in res["output"] and re.search(r"^0\s+0$", res["output"], re.M)
    (Path(s.worktree) / "dirty.txt").write_text("x")
    assert "dirty.txt" in (await call(server, "deploy_status"))["output"]
    assert (await call(server, "list_backups"))["ok"] is False        # directory does not exist yet


async def test_http_health_reports_status_code(local_server):
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    httpd = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _, server = local_server(odoo_url=f"http://127.0.0.1:{httpd.server_port}")
    res = await call(server, "odoo_http_health")
    httpd.shutdown()
    assert res["ok"] and res["output"].startswith("200 ")


# ------------------------------------------------------------------ write tools
@needs_postgres
async def test_backup_dry_run_then_confirm(local_server, env, tmp_path):
    s, server = local_server(enabled_write_tools=ALL_WRITES)
    dry = await call(server, "backup_database")
    assert dry["dry_run"] is True and "pg_dump" in dry["would_run"][0]
    assert not any("pg_dump" in c for c in calls_made(env)) and not Path(s.backup_dir).exists()
    done = await call(server, "backup_database", confirm=True)
    assert done["ok"], done
    dumps = list(Path(s.backup_dir).glob(f"{PG_DB}_*.dump"))
    assert len(dumps) == 1 and dumps[0].stat().st_size > 1000
    assert (await call(server, "list_backups"))["ok"]
    assert (await call(server, "backup_database", db="postgres", confirm=True))["ok"] is False


@needs_postgres
async def test_module_upgrade_requires_a_fresh_backup(local_server, env):
    s, server = local_server(enabled_write_tools=ALL_WRITES)
    args = dict(action="upgrade", modules=["sgc_pdc_management", "sgc_broker_registration"])
    dry = await call(server, "odoo_module_command", **args)
    assert dry["dry_run"] and "-u sgc_pdc_management,sgc_broker_registration" in dry["would_run"][1]
    refused = await call(server, "odoo_module_command", confirm=True, **args)
    assert refused["ok"] is False and "backup" in refused["error"].lower()
    assert not any(" odoo " in f" {c} " for c in calls_made(env))

    await call(server, "backup_database", confirm=True)
    ran = await call(server, "odoo_module_command", confirm=True, **args)
    assert ran["ok"] and ran["errors_found"] == 0 and "restart" in ran["next"].lower()
    assert any("-u sgc_pdc_management,sgc_broker_registration --stop-after-init" in c for c in calls_made(env))

    failing = build_server(s, LocalExecutor(env={**env, "FAKE_ODOO_FAIL": "1"}))
    failed = await call(failing, "odoo_module_command", confirm=True, **args)
    assert failed["ok"] is False and failed["errors_found"] >= 1 and failed["first_errors"]


async def test_module_command_rejects_bad_input(local_server):
    _, server = local_server(enabled_write_tools=ALL_WRITES)
    for bad in (dict(action="uninstall", modules=["x_y"]), dict(action="install", modules=["a;rm -rf /"]),
                dict(action="upgrade", modules=[]), dict(action="upgrade", modules=["ok_mod"], db="postgres")):
        res = await call(server, "odoo_module_command", confirm=True, **bad)
        assert res["ok"] is False, bad


async def test_stale_backup_is_not_good_enough(local_server, env):
    s, server = local_server(enabled_write_tools=ALL_WRITES, backup_max_age_min=30)
    Path(s.backup_dir).mkdir(parents=True)
    old = Path(s.backup_dir) / f"{PG_DB}_20200101_000000.dump"
    old.write_text("x")
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    res = await call(server, "odoo_module_command", action="upgrade", modules=["base"], confirm=True)
    assert res["ok"] is False and "30 minutes" in res["error"]


async def test_deploy_pull_fast_forwards_only(local_server, worktree, tmp_path):
    work, origin = worktree
    s, server = local_server(enabled_write_tools=ALL_WRITES)
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(other), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(other), "config", "user.name", "t"], check=True)
    (other / "b.txt").write_text("2")
    subprocess.run(["git", "-C", str(other), "add", "."], check=True)
    subprocess.run(["git", "-C", str(other), "commit", "-qm", "second"], check=True)
    subprocess.run(["git", "-C", str(other), "push", "-q", "origin", "HEAD:master"], check=True, capture_output=True)

    dry = await call(server, "deploy_pull")
    assert dry["dry_run"] and not (work / "b.txt").exists()
    done = await call(server, "deploy_pull", confirm=True)
    assert done["ok"] and (work / "b.txt").exists() and "second" in done["output"]
    # diverge locally -> a non-fast-forward pull must fail instead of merging
    (work / "c.txt").write_text("3")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-qm", "local only"], check=True)
    (other / "d.txt").write_text("4")
    subprocess.run(["git", "-C", str(other), "add", "."], check=True)
    subprocess.run(["git", "-C", str(other), "commit", "-qm", "third"], check=True)
    subprocess.run(["git", "-C", str(other), "push", "-q", "origin", "HEAD:master"], check=True, capture_output=True)
    diverged = await call(server, "deploy_pull", confirm=True)
    assert diverged["ok"] is False


async def test_restart_needs_confirm(local_server, env):
    _, server = local_server(enabled_write_tools=ALL_WRITES)
    assert (await call(server, "odoo_restart"))["dry_run"]
    assert not any(c.startswith("restart") for c in calls_made(env))
    assert (await call(server, "odoo_restart", confirm=True))["ok"]
    assert any(c == "restart sgc_rent_mt" for c in calls_made(env))


# ------------------------------------------------------------------ audit + executor limits
async def test_every_call_is_audited_without_output(local_server):
    s, server = local_server()
    await call(server, "odoo_logs", lines=5)
    await call(server, "sql_readonly", query_text="select password from res_users")
    lines = [json.loads(l) for l in Path(s.audit_log).read_text().splitlines()]
    assert [l["tool"] for l in lines] == ["odoo_logs", "sql_readonly"]
    assert lines[0]["ok"] is True and lines[1]["ok"] is False and "credential" in lines[1]["note"]
    assert lines[1]["args"]["query_text"] == "select password from res_users"
    assert "hunter2" not in Path(s.audit_log).read_text() and "output" not in lines[0]
    if os.name == "posix":
        assert Path(s.audit_log).stat().st_mode & 0o077 == 0


async def test_executor_enforces_timeout_and_output_cap():
    ex = LocalExecutor()
    slow = await ex.run("sleep 5; echo done", timeout=0.5)
    assert slow.timed_out and not slow.ok
    big = await ex.run("yes abcdefghij | head -c 2000000", max_bytes=5000)
    assert big.truncated and len(big.stdout) <= 5000
    fed = await ex.run("cat", stdin="hello")
    assert fed.ok and fed.stdout == "hello"
