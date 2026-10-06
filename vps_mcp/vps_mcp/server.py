"""FastMCP server: a fixed menu of VPS operations. There is deliberately no generic "run a command" tool."""

from __future__ import annotations

import csv
import functools
import io
import re
import sys
import time

from fastmcp import FastMCP

from . import __version__
from .audit import AuditLog
from .config import ConfigError, Settings
from .executor import Executor, ExecError, ExecResult, SSHExecutor, sh
from .guards import (GuardError, check_readonly_sql, clamp, redact, validate_like, validate_modules,
                     validate_since)

PG_OPTIONS = ("-c default_transaction_read_only=on -c statement_timeout=15000 "
              "-c idle_in_transaction_session_timeout=15000 -c lock_timeout=2000")
ERROR_LINE_RE = re.compile(r"\b(CRITICAL|ERROR|Traceback)\b")


def build_server(settings: Settings, executor: Executor) -> FastMCP:
    mcp = FastMCP("vps", instructions=(
        "Operate the Park Group Odoo VPS. Everything is a fixed, audited operation. Read-only tools are always "
        "available; write tools exist only if the operator enabled them and always need confirm=true after a dry run."))
    audit = AuditLog(settings.audit_log)

    # ------------------------------------------------------------------ plumbing
    def tool(name: str, *, write: bool = False):
        """Register a tool with audit logging, uniform error handling and (for writes) enablement."""
        def decorator(fn):
            @functools.wraps(fn)
            async def wrapper(*args, **kwargs):
                started = time.monotonic()
                ok, note = False, ""
                try:
                    result = await fn(*args, **kwargs)
                    ok = bool(result.get("ok", True)) if isinstance(result, dict) else True
                    note = "dry-run" if isinstance(result, dict) and result.get("dry_run") else ""
                    return result
                except (GuardError, ExecError) as exc:
                    note = f"{type(exc).__name__}: {exc}"
                    return {"ok": False, "error": str(exc)}
                finally:
                    audit.record(name, kwargs, ok=ok, duration_ms=int((time.monotonic() - started) * 1000), note=note)
            return mcp.tool(name=name, annotations={"readOnlyHint": not write, "destructiveHint": write,
                                                    "openWorldHint": False})(wrapper)
        return decorator

    async def run(command: str, *, stdin: str | None = None, timeout: float | None = None) -> ExecResult:
        return await executor.run(command, stdin=stdin, timeout=timeout or settings.command_timeout,
                                  max_bytes=settings.max_output_bytes)

    def shape(res: ExecResult, *, ok_codes: tuple[int, ...] = (0,)) -> dict:
        ok = res.exit_status in ok_codes and not res.timed_out
        out = {"ok": ok, "exit_status": res.exit_status, "output": redact(res.stdout).rstrip()}
        if res.stderr.strip():
            out["stderr"] = redact(res.stderr).rstrip()[-2000:]
        if res.truncated:
            out["truncated"] = True
        if res.timed_out:
            out["timed_out"] = True
        return out

    def pick_db(db: str | None) -> str:
        db = db or settings.db_name
        if db not in settings.dbs:
            raise GuardError(f"Database {db!r} is not allowed. Allowed: {', '.join(settings.dbs)}")
        return db

    def psql(db: str, *, limit: int = 200, readonly: bool = True) -> str:
        if not settings.db_container:
            raise GuardError("VPS_DB_CONTAINER is not configured, so database tools are unavailable.")
        cmd = sh("docker", "exec", "-i", "-e", f"PGOPTIONS={PG_OPTIONS}", settings.db_container,
                 "psql", "-U", settings.pg_user, "-d", db, "-X", "-A", "--csv", "-v", "ON_ERROR_STOP=1", "-f", "-")
        # pipefail keeps psql's own exit status; `head` closing the pipe early (141) is the normal "enough rows" case
        return sh("bash", "-o", "pipefail", "-c", f"{cmd} | head -n {limit + 1}")

    async def query(db: str, sql: str, *, limit: int = 200) -> dict:
        """Run an internal, trusted query (fixed text built here) through the same read-only session."""
        res = await run(psql(db, limit=limit), stdin=sql + "\n")
        out = shape(res, ok_codes=(0, 141))
        if out["ok"] and res.stdout.strip():
            rows = list(csv.reader(io.StringIO(res.stdout)))
            out["row_count"] = max(len(rows) - 1, 0)
        if not out["ok"] and "error" not in out:
            lines = redact(res.stderr).strip().splitlines()
            errors = [ln for ln in lines if ln.lstrip().upper().startswith(("ERROR", "PSQL:", "FATAL"))]
            out["error"] = (errors or lines or ["The database command failed."])[0][:300]
        return out

    # ------------------------------------------------------------------ read-only tools
    @tool("vps_status")
    async def vps_status() -> dict:
        """Uptime, load, memory, disk usage and Docker version of the VPS."""
        cmd = ("uptime; echo '--- memory (MB)'; free -m; echo '--- disk'; df -h / /opt 2>/dev/null; "
               "echo '--- docker'; docker --version")
        return shape(await run(cmd))

    @tool("docker_ps")
    async def docker_ps() -> dict:
        """All containers with image, status and published ports."""
        return shape(await run(sh("docker", "ps", "-a", "--format", "{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}")))

    @tool("odoo_logs")
    async def odoo_logs(lines: int = 200, since: str | None = None, grep: str | None = None) -> dict:
        """Recent Odoo container log lines (secrets redacted). `since` like 30m/2h/1d; `grep` is a case-insensitive
        plain-text filter."""
        lines = clamp(lines, 1, 2000)
        since = validate_since(since)
        argv = ["docker", "logs", "--tail", str(lines if not grep else 5000)]
        if since:
            argv += ["--since", since]
        argv.append(settings.odoo_container)
        cmd = sh(*argv) + " 2>&1"
        if grep:
            if len(grep) > 100 or "\n" in grep or "\x00" in grep:
                raise GuardError("The filter must be a single line of at most 100 characters.")
            cmd += f" | grep -i -F -- {sh(grep)} | tail -n {lines}"
        return shape(await run(cmd))

    @tool("odoo_modules")
    async def odoo_modules(like: str = "sgc%", db: str | None = None) -> dict:
        """Installed state and version of Odoo modules whose name matches the SQL LIKE pattern (default sgc%)."""
        like = validate_like(like)
        return await query(pick_db(db), "select name, state, latest_version, to_char(write_date, 'YYYY-MM-DD HH24:MI') "
                           f"as updated from ir_module_module where name like '{like}' order by name")

    @tool("odoo_cron_status")
    async def odoo_cron_status(db: str | None = None) -> dict:
        """Scheduled jobs with next/last run, to spot jobs that stopped running."""
        return await query(pick_db(db), "select id, cron_name, active, nextcall, lastcall, interval_number, "
                           "interval_type from ir_cron order by nextcall limit 80")

    @tool("odoo_mail_queue")
    async def odoo_mail_queue(db: str | None = None) -> dict:
        """Outgoing mail queue: counts per state and the age of the oldest unsent mail."""
        return await query(pick_db(db), "select state, count(*) as mails, min(create_date) as oldest from mail_mail "
                           "group by state order by state")

    @tool("odoo_http_health")
    async def odoo_http_health() -> dict:
        """HTTP status and response time of the Odoo login page, as seen from the VPS itself."""
        cmd = sh("curl", "-s", "-m", "10", "-o", "/dev/null", "-w", "%{http_code} %{time_total}s",
                 f"{settings.odoo_url}/web/login")
        return shape(await run(cmd))

    @tool("list_databases")
    async def list_databases() -> dict:
        """Databases on the PostgreSQL server with their size."""
        res = await run(psql("postgres", limit=100),
                        stdin="select datname, pg_size_pretty(pg_database_size(datname)) as size from pg_database "
                              "where not datistemplate order by datname\n")
        return shape(res, ok_codes=(0, 141))

    @tool("sql_readonly")
    async def sql_readonly(query_text: str, db: str | None = None, limit: int = 200) -> dict:
        """Run ONE read-only SELECT/WITH/EXPLAIN/SHOW query (CSV result, at most `limit` rows, 15 s timeout).
        Credential data (passwords, API keys, tokens, system secrets) is blocked."""
        sql = check_readonly_sql(query_text)
        limit = clamp(limit, 1, 1000)
        return await query(pick_db(db), sql, limit=limit)

    @tool("deploy_status")
    async def deploy_status() -> dict:
        """Git state of the deployed worktree: current commit, how far behind/ahead of upstream, local changes."""
        w = settings.worktree
        cmd = (f"{sh('git', '-C', w, 'fetch', '-q')} 2>&1; echo '--- head'; "
               f"{sh('git', '-C', w, 'log', '-1', '--format=%h %ad %an %s', '--date=iso')}; echo '--- ahead/behind (HEAD...upstream)'; "
               f"{sh('git', '-C', w, 'rev-list', '--left-right', '--count', 'HEAD...@{u}')} 2>&1; echo '--- local changes'; "
               f"{sh('git', '-C', w, 'status', '--short')} | head -n 20")
        return shape(await run(cmd))

    @tool("list_backups")
    async def list_backups() -> dict:
        """Database dumps in the backup directory, newest first."""
        inner = f"{sh('ls', '-lht', '--time-style=long-iso', settings.backup_dir)} 2>&1 | head -n 30"
        return shape(await run(sh("bash", "-o", "pipefail", "-c", inner)))

    # ------------------------------------------------------------------ write tools (opt-in)
    def gate(tool_name: str, confirm: bool, commands: list[str]) -> dict | None:
        """Dry run unless confirm=True. Returns the dry-run answer, or None when the caller may proceed."""
        if confirm:
            return None
        return {"ok": True, "dry_run": True, "tool": tool_name,
                "would_run": [redact(c) for c in commands],
                "message": "Nothing was changed. Call again with confirm=true to run exactly this."}

    if "backup_database" in settings.enabled_write_tools:
        @tool("backup_database", write=True)
        async def backup_database(db: str | None = None, confirm: bool = False) -> dict:
            """pg_dump (custom format) of one database into the backup directory. Needs confirm=true."""
            db = pick_db(db)
            if not settings.db_container:
                raise GuardError("VPS_DB_CONTAINER is not configured.")
            stamp = time.strftime("%Y%m%d_%H%M%S")
            target = f"{settings.backup_dir}/{db}_{stamp}.dump"
            cmd = (f"{sh('mkdir', '-p', settings.backup_dir)} && "
                   f"{sh('docker', 'exec', '-u', 'postgres', settings.db_container, 'pg_dump', '-Fc', '-d', db)} > {sh(target)} "
                   f"&& {sh('ls', '-l', target)}")
            dry = gate("backup_database", confirm, [cmd])
            if dry:
                return dry
            return shape(await run(cmd, timeout=900))

    if "deploy_pull" in settings.enabled_write_tools:
        @tool("deploy_pull", write=True)
        async def deploy_pull(confirm: bool = False) -> dict:
            """Fast-forward the deployed worktree to its upstream (git pull --ff-only). Does not restart anything."""
            cmd = (f"{sh('git', '-C', settings.worktree, 'pull', '--ff-only')} 2>&1 && "
                   f"{sh('git', '-C', settings.worktree, 'log', '-3', '--format=%h %s')}")
            dry = gate("deploy_pull", confirm, [cmd])
            return dry or shape(await run(cmd, timeout=300))

    if "odoo_module_command" in settings.enabled_write_tools:
        @tool("odoo_module_command", write=True)
        async def odoo_module_command(action: str, modules: list[str], db: str | None = None,
                                      confirm: bool = False) -> dict:
            """Install ('install') or upgrade ('upgrade') modules in a database with `odoo -i/-u ... --stop-after-init`
            inside the Odoo container. Refuses unless a backup of that database is younger than the configured age."""
            if action not in ("install", "upgrade"):
                raise GuardError("action must be 'install' or 'upgrade'.")
            modules = validate_modules(modules)
            db = pick_db(db)
            flag = "-i" if action == "install" else "-u"
            fresh = sh("find", settings.backup_dir, "-maxdepth", "1", "-name", f"{db}_*.dump", "-mmin",
                       f"-{settings.backup_max_age_min}")
            odoo_cmd = sh("docker", "exec", settings.odoo_container, "odoo", "-d", db, flag, ",".join(modules),
                          "--stop-after-init", "--no-http", "--log-level=warn")
            inner = f"{odoo_cmd} 2>&1 | tail -n 150"
            cmd = sh("bash", "-o", "pipefail", "-c", inner)
            dry = gate("odoo_module_command", confirm, [fresh, cmd])
            if dry:
                return dry
            recent = await run(fresh)
            if not recent.stdout.strip():
                return {"ok": False, "error": f"No backup of {db} newer than {settings.backup_max_age_min} minutes "
                        "was found. Run backup_database first."}
            res = await run(cmd, timeout=settings.long_timeout)
            out = shape(res)
            errors = [ln for ln in res.stdout.splitlines() if ERROR_LINE_RE.search(ln)]
            out["errors_found"] = len(errors)
            out["ok"] = res.ok and not errors
            if errors:
                out["first_errors"] = [redact(e)[:300] for e in errors[:5]]
            out["next"] = "Restart Odoo (odoo_restart) so the running workers load the new code."
            return out

    if "odoo_restart" in settings.enabled_write_tools:
        @tool("odoo_restart", write=True)
        async def odoo_restart(confirm: bool = False) -> dict:
            """Restart the Odoo container. Active users lose their current request."""
            cmd = (f"{sh('docker', 'restart', settings.odoo_container)} && "
                   f"{sh('docker', 'ps', '--filter', f'name={settings.odoo_container}', '--format', '{{.Names}} {{.Status}}')}")
            dry = gate("odoo_restart", confirm, [cmd])
            return dry or shape(await run(cmd, timeout=180))

    return mcp


async def check_connection(settings: Settings) -> int:
    executor = SSHExecutor(settings)
    try:
        res = await executor.run("echo connected as $(whoami) on $(hostname)", timeout=20)
        print(res.stdout.strip() or res.stderr.strip())
        return 0 if res.ok else 1
    except ExecError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        await executor.close()


def main() -> None:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        print(f"vps-mcp configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    if "--check" in sys.argv:
        import asyncio
        raise SystemExit(asyncio.run(check_connection(settings)))
    build_server(settings, SSHExecutor(settings)).run()
