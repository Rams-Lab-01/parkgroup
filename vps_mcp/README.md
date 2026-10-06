# VPS MCP server (Park Group Odoo VPS)

Lets Claude (Claude Code, Claude Desktop, any MCP client) inspect and - if you allow it - deploy to the VPS that
runs Odoo, **without giving it a shell**.

## Design rules

* **A fixed menu, not a terminal.** There is no "run this command" tool. Every operation is a fixed command template;
  every value you can influence (database, module names, log filter, time window) is validated and shell-quoted.
* **Read-only by default.** 11 read-only tools are always available. The 4 write tools do not even exist for the model
  unless you list them in `VPS_MCP_ENABLE`, and each then needs `confirm=true` after a dry run that prints the exact command.
* **Host keys are always verified** against `VPS_KNOWN_HOSTS`. A changed or unknown host key is refused (no
  trust-on-first-use). Password logins and agent forwarding are never used.
* **Secrets never leave the box:** log output is redacted; SQL touching passwords, API keys, tokens or
  `ir_config_parameter` is refused; the database session is read-only (`default_transaction_read_only`, 15 s timeout).
* **Everything is audited** to `~/.vps_mcp/audit.jsonl` (tool, arguments, ok/failed, duration - never the output).
* **Safe upgrades:** `odoo_module_command` refuses unless a backup of that database is younger than
  `VPS_BACKUP_MAX_AGE_MIN`; `deploy_pull` is fast-forward only.

## Tools

| Read-only | What it returns |
|---|---|
| `vps_status` | uptime, load, memory, disk, Docker version |
| `docker_ps` | containers, status, ports |
| `odoo_logs(lines, since, grep)` | recent Odoo log lines, redacted |
| `odoo_modules(like)` | installed state/version of modules (default `sgc%`) |
| `odoo_cron_status` | scheduled jobs: next/last run |
| `odoo_mail_queue` | outgoing mail counts and oldest unsent |
| `odoo_http_health` | HTTP code and latency of `/web/login` from the VPS |
| `list_databases` | databases and sizes |
| `sql_readonly(query_text, limit)` | one SELECT/WITH/EXPLAIN/SHOW query, CSV, max 1000 rows |
| `deploy_status` | deployed commit, ahead/behind upstream, local changes |
| `list_backups` | database dumps in the backup directory |

| Write (opt-in, `confirm=true`) | What it does |
|---|---|
| `backup_database` | `pg_dump -Fc` into the backup directory |
| `deploy_pull` | `git pull --ff-only` in the worktree |
| `odoo_module_command(action, modules)` | `odoo -i/-u ... --stop-after-init` in the Odoo container (needs a fresh backup) |
| `odoo_restart` | restart the Odoo container |

Typical release: `deploy_status` -> `backup_database` -> `deploy_pull` -> `odoo_module_command(upgrade, [...])` ->
`odoo_restart` -> `odoo_http_health` + `odoo_logs(since="10m", grep="error")` + `odoo_modules`.

## Set-up (on the machine where you run Claude, not on the VPS)

```bash
cd vps_mcp && pip install -e .
ssh-keygen -t ed25519 -f ~/.ssh/vps_mcp_ed25519            # use a passphrase
ssh-copy-id -i ~/.ssh/vps_mcp_ed25519.pub mcp@<vps>        # or add it to the user's authorized_keys
ssh-keyscan -p 22 <vps> > ~/.ssh/vps_mcp_known_hosts       # then CHECK the fingerprint against your provider's panel
ssh-keygen -lf ~/.ssh/vps_mcp_known_hosts
cp .env.example .env   # fill it in, then:  set -a; . ./.env; set +a
python -m vps_mcp --check                                   # "connected as mcp on <host>"
```

Claude Code: `claude mcp add vps --env-file .env -- python -m vps_mcp`
Claude Desktop (`claude_desktop_config.json`):

```json
{ "mcpServers": { "vps": { "command": "python", "args": ["-m", "vps_mcp"], "cwd": "/path/to/parkgroup/vps_mcp",
  "env": { "VPS_HOST": "...", "VPS_USER": "mcp", "VPS_SSH_KEY": "...", "VPS_KNOWN_HOSTS": "...",
           "VPS_DB_NAME": "sgc_mt_parkgroup", "VPS_DB_CONTAINER": "..." } } } }
```

## Hardening (recommended)

1. **Dedicated Linux user** `mcp` on the VPS, used for nothing else, with its own key (revocable in one line).
2. **Be aware:** to run `docker` commands that user needs Docker access, and membership of the `docker` group is
   effectively root. The MCP server only ever sends its fixed commands, but the *key* itself could do more if it leaked.
   Protect the key (passphrase, `chmod 600`, never in git). For stronger isolation put a Docker socket proxy
   (e.g. `tecnativa/docker-socket-proxy`, allowing only `CONTAINERS`, `EXEC` and `POST` as needed) in front of the
   socket, or give the user passwordless `sudo` for an explicit list of commands only.
3. **Restricted database role:** run `sql/create_readonly_role.sql` in the Odoo database and set `VPS_PG_USER=mcp_ro`.
   Credential columns and system secrets then cannot be read at all, whatever query is sent.
4. Keep `VPS_MCP_ENABLE` empty day-to-day; enable writes only for the session in which you deploy.
5. Review `~/.vps_mcp/audit.jsonl` now and then; rotate the key if a laptop is lost.

## Tests

```bash
pip install -e '.[test]'
pytest                      # guards, config, SSH (real local SSH server), tools (fake docker + real PostgreSQL)
```
The tools tests need a PostgreSQL that holds an Odoo database (`TEST_PG_HOST`, `TEST_PG_PORT`, `TEST_PG_DB`); without
it those tests are skipped. The SSH tests run an in-process SSH server, including a tampered host key and a wrong client key.
