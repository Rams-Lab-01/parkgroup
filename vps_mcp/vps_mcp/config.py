"""Settings, read from environment variables (see .env.example). Nothing secret has a default."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

WRITE_TOOLS = ("backup_database", "deploy_pull", "odoo_module_command", "odoo_restart")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")


class ConfigError(Exception):
    """The configuration is missing or unsafe; the server refuses to start."""


@dataclass(frozen=True)
class Settings:
    host: str
    user: str
    key_path: str
    known_hosts: str
    db_name: str
    port: int = 22
    key_passphrase: str | None = None
    worktree: str = "/opt/odoo/deploy/sgc-rent-mt"
    odoo_container: str = "sgc_rent_mt"
    db_container: str = ""
    pg_user: str = "odoo"
    odoo_url: str = "http://127.0.0.1:8069"
    backup_dir: str = "/opt/backups/odoo"
    backup_max_age_min: int = 60
    allowed_dbs: tuple[str, ...] = ()
    enabled_write_tools: frozenset[str] = field(default_factory=frozenset)
    audit_log: str = "~/.vps_mcp/audit.jsonl"
    max_output_bytes: int = 60_000
    command_timeout: float = 60.0
    long_timeout: float = 1800.0

    @property
    def dbs(self) -> tuple[str, ...]:
        return self.allowed_dbs or (self.db_name,)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)

        def need(key: str) -> str:
            value = (env.get(key) or "").strip()
            if not value:
                raise ConfigError(f"Environment variable {key} is required.")
            return value

        known_hosts = os.path.expanduser(need("VPS_KNOWN_HOSTS"))
        if not Path(known_hosts).is_file():
            raise ConfigError(
                f"VPS_KNOWN_HOSTS ({known_hosts}) does not exist. Host keys are always verified; create the file "
                "with `ssh-keyscan -p 22 <host> > <file>` and check the fingerprint against your provider's panel.")
        key_path = os.path.expanduser(need("VPS_SSH_KEY"))
        if not Path(key_path).is_file():
            raise ConfigError(f"VPS_SSH_KEY ({key_path}) does not exist.")
        mode = Path(key_path).stat().st_mode & 0o077
        if mode and os.name == "posix":
            raise ConfigError(f"VPS_SSH_KEY ({key_path}) is readable by other users; run `chmod 600` on it.")

        enabled = {t.strip() for t in (env.get("VPS_MCP_ENABLE") or "").split(",") if t.strip()}
        unknown = enabled - set(WRITE_TOOLS)
        if unknown:
            raise ConfigError(f"VPS_MCP_ENABLE contains unknown tools: {sorted(unknown)}. Valid: {list(WRITE_TOOLS)}")

        settings = cls(
            host=need("VPS_HOST"), user=need("VPS_USER"), key_path=key_path, known_hosts=known_hosts,
            db_name=need("VPS_DB_NAME"), port=int(env.get("VPS_PORT") or 22),
            key_passphrase=env.get("VPS_SSH_KEY_PASSPHRASE") or None,
            worktree=env.get("VPS_WORKTREE") or cls.worktree,
            odoo_container=env.get("VPS_ODOO_CONTAINER") or cls.odoo_container,
            db_container=env.get("VPS_DB_CONTAINER") or "",
            pg_user=env.get("VPS_PG_USER") or cls.pg_user,
            odoo_url=(env.get("VPS_ODOO_URL") or cls.odoo_url).rstrip("/"),
            backup_dir=env.get("VPS_BACKUP_DIR") or cls.backup_dir,
            backup_max_age_min=int(env.get("VPS_BACKUP_MAX_AGE_MIN") or 60),
            allowed_dbs=tuple(d.strip() for d in (env.get("VPS_ALLOWED_DBS") or "").split(",") if d.strip()),
            enabled_write_tools=frozenset(enabled),
            audit_log=env.get("VPS_MCP_AUDIT_LOG") or cls.audit_log,
            max_output_bytes=int(env.get("VPS_MCP_MAX_OUTPUT") or 60_000),
            command_timeout=float(env.get("VPS_MCP_TIMEOUT") or 60),
        )
        for label, value in (("VPS_ODOO_CONTAINER", settings.odoo_container), ("VPS_DB_CONTAINER", settings.db_container),
                             ("VPS_DB_NAME", settings.db_name), ("VPS_PG_USER", settings.pg_user)):
            if value and not NAME_RE.match(value):
                raise ConfigError(f"{label} contains unsupported characters: {value!r}")
        for db in settings.dbs:
            if not NAME_RE.match(db):
                raise ConfigError(f"Database name {db!r} contains unsupported characters.")
        for path in (settings.worktree, settings.backup_dir):
            if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path):
                raise ConfigError(f"Path {path!r} must be absolute and use only letters, digits, _ . / -")
        return settings
