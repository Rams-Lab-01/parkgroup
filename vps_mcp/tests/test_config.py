import os

import pytest

from vps_mcp.config import ConfigError, Settings


@pytest.fixture
def good(tmp_path):
    key = tmp_path / "id"
    key.write_text("k")
    key.chmod(0o600)
    kh = tmp_path / "kh"
    kh.write_text("x")
    return {"VPS_HOST": "1.2.3.4", "VPS_USER": "deploy", "VPS_SSH_KEY": str(key), "VPS_KNOWN_HOSTS": str(kh),
            "VPS_DB_NAME": "sgc_mt_parkgroup", "VPS_DB_CONTAINER": "sgc_rent_mt_db"}


def test_defaults_are_read_only_and_safe(good):
    s = Settings.from_env(good)
    assert s.enabled_write_tools == frozenset()
    assert s.dbs == ("sgc_mt_parkgroup",)
    assert s.odoo_container == "sgc_rent_mt"


def test_required_values(good):
    for key in ("VPS_HOST", "VPS_USER", "VPS_SSH_KEY", "VPS_KNOWN_HOSTS", "VPS_DB_NAME"):
        env = dict(good)
        env.pop(key)
        with pytest.raises(ConfigError):
            Settings.from_env(env)


def test_missing_known_hosts_is_refused_with_instructions(good):
    good["VPS_KNOWN_HOSTS"] = "/nonexistent/kh"
    with pytest.raises(ConfigError, match="ssh-keyscan"):
        Settings.from_env(good)


@pytest.mark.skipif(os.name != "posix", reason="permission bits")
def test_world_readable_key_is_refused(good):
    os.chmod(good["VPS_SSH_KEY"], 0o644)
    with pytest.raises(ConfigError, match="chmod 600"):
        Settings.from_env(good)


def test_write_tools_are_validated(good):
    good["VPS_MCP_ENABLE"] = "backup_database, odoo_restart"
    assert Settings.from_env(good).enabled_write_tools == {"backup_database", "odoo_restart"}
    good["VPS_MCP_ENABLE"] = "rm_rf"
    with pytest.raises(ConfigError, match="unknown tools"):
        Settings.from_env(good)


@pytest.mark.parametrize("key,value", [("VPS_ODOO_CONTAINER", "a;b"), ("VPS_DB_NAME", "x y"),
                                       ("VPS_WORKTREE", "relative/path"), ("VPS_BACKUP_DIR", "/x; rm -rf /"),
                                       ("VPS_ALLOWED_DBS", "ok,bad name")])
def test_injection_through_settings_is_refused(good, key, value):
    good[key] = value
    with pytest.raises(ConfigError):
        Settings.from_env(good)
