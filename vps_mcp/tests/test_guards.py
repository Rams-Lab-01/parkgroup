import pytest

from vps_mcp.guards import (GuardError, check_readonly_sql, clamp, redact, validate_like, validate_modules,
                            validate_since)

ALLOWED = [
    "select 1",
    "SELECT id, name FROM res_partner WHERE active ORDER BY id LIMIT 5;",
    "with x as (select 1 as a) select a from x",
    "select count(*) from sale_contract",
    "select 'drop table x; delete from y' as text",                       # keywords inside a string are data
    "select name from ir_module_module where name like 'sgc%'",
    "select * from sale_contract",                                         # star is fine outside res_users
    "explain select * from res_partner",
    "explain analyze select 1",
    "show server_version",
    "select 1 -- trailing comment",
    "/* leading */ select 1",
    "select \"name\" from res_partner",
    "select 'it''s fine'",
    "select u.login from res_users u where u.active",
]

REFUSED = [
    ("", "Empty"),
    ("   ", "Empty"),
    ("select 1; drop table res_partner", "one statement"),
    ("select 1; select 2", "one statement"),
    ("drop table res_partner", "Only SELECT"),
    ("delete from res_partner", "Only SELECT"),
    ("insert into res_partner(name) values ('x')", "Only SELECT"),
    ("update res_partner set name='x'", "Only SELECT"),
    ("with d as (delete from res_partner returning *) select * from d", "DELETE"),
    ("select * into newt from res_partner", "INTO"),
    ("/* hide */ drop table x", "Only SELECT"),
    ("select 1 /* x */; /* y */ drop table z", "one statement"),
    ("copy res_partner to program 'x'", "Only SELECT"),
    ("select pg_read_file('/etc/passwd')", "pg_read_file"),
    ("select pg_sleep(100)", "pg_sleep"),
    ("select lo_import('/etc/passwd')", "lo_import"),
    ("select dblink('x','y')", "dblink"),
    ("select set_config('a','b',false)", "SET"),
    ("select nextval('seq')", "nextval"),
    ("select * from res_partner for update", "not allowed"),
    ("select * from pg_authid", "pg_authid"),
    ("select analyze from x", "ANALYZE"),
    ("select $$a$$", "dollar"),
    ("select $1", "dollar"),
    ("select E'a\\'b'", "Escape"),
    ("select 'unterminated", "Unterminated"),
    ("select 1 /* never closed", "Unterminated"),
    ("select \x00 1", "Invalid character"),
    ("x" * 6000, "too long"),
    ("select password from res_users", "credential"),
    ("select key from res_users_apikeys", "credential"),
    ("select value from ir_config_parameter where key='database.secret'", "credential"),
    ("select access_token from ir_attachment", "credential"),
    ("select * from res_users", "explicit columns"),
    ("select u.* from res_users u", "explicit columns"),
    ("select totp_secret from res_users", "credential"),
    ("grant all on res_partner to public", "Only SELECT"),
    ("vacuum", "Only SELECT"),
    ("call my_proc()", "Only SELECT"),
    ("do $$ begin end $$", "dollar"),
    ("select 1 where 1=1 union all select 2; --", None),                  # a lone trailing comment is fine
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed(sql):
    assert check_readonly_sql(sql)


@pytest.mark.parametrize("sql,fragment", [r for r in REFUSED if r[1]])
def test_refused(sql, fragment):
    with pytest.raises(GuardError) as exc:
        check_readonly_sql(sql)
    assert fragment.lower() in str(exc.value).lower()


def test_trailing_semicolon_is_stripped():
    assert check_readonly_sql("select 1;  ") == "select 1"


def test_identifier_validators():
    assert validate_modules(["sgc_pdc_management", "sgc_pdc_management", "base"]) == ["sgc_pdc_management", "base"]
    for bad in (["Bad"], ["a;b"], ["x y"], [""], [], ["a"] * 0, ["m" + str(i) for i in range(21)], ["../x"], ["a-b"]):
        with pytest.raises(GuardError):
            validate_modules(bad)
    assert validate_like("sgc%") == "sgc%"
    for bad in ("sgc'; drop", "A%", "", "a b", "x" * 65):
        with pytest.raises(GuardError):
            validate_like(bad)
    assert validate_since("30m") == "30m" and validate_since(None) is None
    for bad in ("0m", "5", "1w", "1h; ls", "$(id)"):
        with pytest.raises(GuardError):
            validate_since(bad)
    assert clamp(99999, 1, 2000) == 2000 and clamp(-5, 1, 10) == 1


def test_redaction():
    text = ("db_password = hunter2\nAuthorization: Bearer abcdef1234567890\nuser=odoo password=\"s3 cr3t\"\n"
            "postgres://odoo:SuperSecret@db:5432/x\napi_key: ABCDEF\n" + "a" * 40 + "\n"
            "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\nnormal line stays")
    out = redact(text)
    for secret in ("hunter2", "abcdef1234567890", "s3 cr3t", "SuperSecret", "ABCDEF", "AAAA"):
        assert secret not in out
    assert "normal line stays" in out and "postgres://odoo:[redacted]@db" in out
