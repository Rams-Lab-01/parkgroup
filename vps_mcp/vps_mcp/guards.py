"""Input validation, the read-only SQL gate and output redaction. Pure functions, no I/O."""

from __future__ import annotations

import re

MAX_SQL_CHARS = 5000


class GuardError(Exception):
    """A request was refused before anything ran on the server."""


# ---------------------------------------------------------------- simple identifiers
_MODULE_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_LIKE_RE = re.compile(r"^[a-z0-9_%]{1,64}$")
_SINCE_RE = re.compile(r"^[1-9][0-9]{0,3}[smhd]$")


def validate_modules(modules: list[str]) -> list[str]:
    if not modules or len(modules) > 20:
        raise GuardError("Give between 1 and 20 module names.")
    for name in modules:
        if not _MODULE_RE.match(name):
            raise GuardError(f"Invalid module name: {name!r}")
    return list(dict.fromkeys(modules))


def validate_like(pattern: str) -> str:
    if not _LIKE_RE.match(pattern or ""):
        raise GuardError("The pattern may only contain lowercase letters, digits, '_' and '%'.")
    return pattern


def validate_since(value: str | None) -> str | None:
    if value in (None, ""):
        return None
    if not _SINCE_RE.match(value):
        raise GuardError("`since` must look like 30m, 2h or 1d.")
    return value


def clamp(value: int, low: int, high: int) -> int:
    return max(low, min(int(value), high))


# ---------------------------------------------------------------- read-only SQL gate
_FORBIDDEN_WORDS = (
    "insert", "update", "delete", "drop", "alter", "create", "truncate", "grant", "revoke", "copy", "call", "do",
    "execute", "prepare", "deallocate", "vacuum", "reindex", "cluster", "refresh", "lock", "listen", "notify",
    "unlisten", "reset", "set", "into", "merge", "comment", "security", "import", "load", "discard", "checkpoint",
)
_FORBIDDEN_FUNCTIONS = (
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_ls_logdir", "pg_ls_waldir", "pg_ls_tmpdir",
    "pg_stat_file", "lo_import", "lo_export", "lo_get", "lo_put", "dblink", "pg_sleep", "pg_terminate_backend",
    "pg_cancel_backend", "pg_reload_conf", "pg_rotate_logfile", "set_config", "nextval", "setval",
    "pg_advisory_lock", "pg_try_advisory_lock", "pg_logical_emit_message", "pg_create_restore_point",
    "pg_authid", "pg_shadow", "pg_user_mappings", "pg_file_settings", "pg_hba_file_rules",
)
_CREDENTIAL_PATTERNS = (
    r"\bres_users_apikeys\b", r"\bir_config_parameter\b", r"\bauth_totp", r"\bres_users_identitycheck\b",
    r"oauth", r"password", r"passwd", r"api_?key", r"secret", r"token", r"key_hash", r"crypt",
)
_STAR_RE = re.compile(r"select\s+(distinct\s+)?([a-z_][a-z0-9_]*\.)?\*")


def _skeleton(sql: str) -> str:
    """Drop comments and blank out the inside of string literals / quoted identifiers.

    Anything the database would treat as code stays visible to the keyword checks; anything it would treat as
    data is hidden, so `select 'drop table x'` is allowed and `/* ok */ drop table x` is not.
    """
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if ch == "-" and nxt == "-":
            end = sql.find("\n", i)
            i = n if end == -1 else end
            out.append(" ")
        elif ch == "/" and nxt == "*":
            depth, i = 1, i + 2
            while i < n and depth:
                if sql.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif sql.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
            if depth:
                raise GuardError("Unterminated comment.")
            out.append(" ")
        elif ch in ("'", '"'):
            quote = ch
            out.append(quote)
            i += 1
            while True:
                if i >= n:
                    raise GuardError("Unterminated quoted text.")
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:     # doubled quote = escaped quote
                        i += 2
                        out.append("  ")
                        continue
                    i += 1
                    break
                out.append(" ")
                i += 1
            out.append(quote)
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def check_readonly_sql(sql: str) -> str:
    """Return the statement to run, or raise GuardError. This is a first line of defence: the database
    session itself is also read-only and should use a restricted role (see sql/create_readonly_role.sql)."""
    if not sql or not sql.strip():
        raise GuardError("Empty query.")
    if len(sql) > MAX_SQL_CHARS:
        raise GuardError(f"Query too long (maximum {MAX_SQL_CHARS} characters).")
    if "\x00" in sql:
        raise GuardError("Invalid character in query.")
    if re.search(r"(?<![A-Za-z0-9_])e'", sql, re.I) or "$" in re.sub(r"'[^']*'", "''", sql):
        raise GuardError("Escape strings and dollar quoting are not allowed.")
    skeleton = _skeleton(sql).strip()
    body = skeleton.rstrip(";").strip()
    if ";" in body:
        raise GuardError("Only one statement is allowed.")
    low = body.lower()
    first = re.match(r"[a-z]+", low)
    if not first or first.group(0) not in ("select", "with", "explain", "show", "values", "table"):
        raise GuardError("Only SELECT, WITH, EXPLAIN, SHOW and VALUES statements are allowed.")
    for word in _FORBIDDEN_WORDS:
        if re.search(rf"(?<![a-z0-9_]){word}(?![a-z0-9_])", low):
            raise GuardError(f"The keyword '{word.upper()}' is not allowed (read-only access).")
    if re.search(r"for\s+(no\s+key\s+)?(update|share)", low):
        raise GuardError("Row locking is not allowed.")
    if first.group(0) != "explain" and re.search(r"(?<![a-z0-9_])analyze(?![a-z0-9_])", low):
        raise GuardError("ANALYZE is only allowed inside EXPLAIN.")
    for func in _FORBIDDEN_FUNCTIONS:
        if func in low:
            raise GuardError(f"'{func}' is not allowed.")
    for pattern in _CREDENTIAL_PATTERNS:
        if re.search(pattern, low):
            raise GuardError("The query touches credential or secret data, which this tool never returns.")
    if re.search(r"(?<![a-z0-9_])res_users(?![a-z0-9_])", low) and _STAR_RE.search(low):
        raise GuardError("Select explicit columns from res_users (SELECT * would include credential columns).")
    return sql.strip().rstrip(";")


# ---------------------------------------------------------------- output redaction
_REDACTIONS = (
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), "Bearer [redacted]"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[private key removed]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|authorization|db_password|admin_passwd)"
                r"(\s*[=:]\s*|\s+)(\"[^\"]*\"|'[^']*'|[^\s,;\"']+)"), r"\1\2[redacted]"),
    (re.compile(r"(?i)\b(postgres(?:ql)?|mysql|amqp|redis)://([^:/\s@]+):([^@\s]+)@"), r"\1://\2:[redacted]@"),
    (re.compile(r"\b[0-9a-f]{40,}\b"), "[hex redacted]"),
)


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text
