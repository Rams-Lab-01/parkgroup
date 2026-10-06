import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from vps_mcp.config import Settings
from vps_mcp.executor import LocalExecutor
from vps_mcp.server import build_server

SHIMS = str(Path(__file__).parent / "shims")
PG_HOST = os.environ.get("TEST_PG_HOST", "/tmp")
PG_PORT = os.environ.get("TEST_PG_PORT", "5433")
PG_DB = os.environ.get("TEST_PG_DB", "it5")


def _pg_available() -> bool:
    if not shutil.which("psql"):
        return False
    r = subprocess.run(["psql", "-h", PG_HOST, "-p", PG_PORT, "-d", PG_DB, "-Atc", "select count(*) from ir_cron"],
                       capture_output=True, text=True)
    return r.returncode == 0


needs_postgres = pytest.mark.skipif(not _pg_available(), reason="needs a local PostgreSQL with an Odoo database "
                                    "(set TEST_PG_HOST / TEST_PG_PORT / TEST_PG_DB)")


@pytest.fixture
def env(tmp_path):
    log = tmp_path / "odoo.log"
    log.write_text("2026-01-01 INFO started\n2026-01-01 ERROR something failed password=hunter2 for user\n"
                   "2026-01-01 INFO postgres://odoo:SuperSecret@db:5432/x connected\n" + "filler line\n" * 5)
    e = dict(os.environ)
    e.update(PATH=f"{SHIMS}:{e['PATH']}", FAKE_DOCKER_CALLS=str(tmp_path / "calls.log"),
             FAKE_DOCKER_LOG_FILE=str(log), TEST_PG_HOST=PG_HOST, TEST_PG_PORT=PG_PORT)
    return e


@pytest.fixture
def worktree(tmp_path):
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    for cmd in (["git", "-C", str(work), "config", "user.email", "t@t"], ["git", "-C", str(work), "config", "user.name", "t"]):
        subprocess.run(cmd, check=True)
    (work / "a.txt").write_text("1")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True)
    subprocess.run(["git", "-C", str(work), "commit", "-qm", "first"], check=True)
    subprocess.run(["git", "-C", str(work), "push", "-q", "origin", "HEAD:master"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "branch", "-q", "--set-upstream-to=origin/master"], check=True, capture_output=True)
    return work, origin


@pytest.fixture
def make_settings(tmp_path, worktree):
    def _make(**over):
        base = dict(host="h", user="u", key_path="k", known_hosts="kh", db_name=PG_DB, db_container="pg",
                    audit_log=str(tmp_path / "audit.jsonl"), worktree=str(worktree[0]),
                    backup_dir=str(tmp_path / "backups"), odoo_url="http://127.0.0.1:1", command_timeout=30)
        base.update(over)
        return Settings(**base)
    return _make


@pytest.fixture
def local_server(make_settings, env):
    def _build(**over):
        s = make_settings(**over)
        return s, build_server(s, LocalExecutor(env=env))
    return _build
