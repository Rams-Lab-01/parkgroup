-- Restricted, read-only database role for the VPS MCP server.
--
-- Run ONCE per Odoo database as a PostgreSQL superuser, e.g.
--   docker exec -i <db-container> psql -U postgres -d <database> -v ON_ERROR_STOP=1 < create_readonly_role.sql
-- then set VPS_PG_USER=mcp_ro in the MCP server's environment.
--
-- What it does: the role can only SELECT; every column that looks like a credential (passwords, tokens, API keys,
-- TOTP secrets, ...) and the tables that hold system secrets are not readable at all, so even a query that got past
-- the server-side checks could not return them.

DO $$ BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mcp_ro') THEN
        CREATE ROLE mcp_ro LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END $$;

ALTER ROLE mcp_ro SET default_transaction_read_only = on;
ALTER ROLE mcp_ro SET statement_timeout = '15s';
ALTER ROLE mcp_ro CONNECTION LIMIT 5;

REVOKE ALL ON ALL TABLES IN SCHEMA public FROM mcp_ro;
GRANT CONNECT ON DATABASE :"DBNAME" TO mcp_ro;
GRANT USAGE ON SCHEMA public TO mcp_ro;

DO $$
DECLARE
    t record;
    cols text;
    blocked_tables text[] := ARRAY['ir_config_parameter', 'res_users_apikeys', 'auth_totp_device',
                                   'res_users_identitycheck', 'auth_oauth_provider', 'ir_cron_progress'];
BEGIN
    FOR t IN SELECT table_name FROM information_schema.tables
             WHERE table_schema = 'public' AND table_type = 'BASE TABLE' LOOP
        CONTINUE WHEN t.table_name = ANY (blocked_tables);
        SELECT string_agg(quote_ident(column_name), ', ') INTO cols
          FROM information_schema.columns
         WHERE table_schema = 'public' AND table_name = t.table_name
           AND column_name !~* '(password|passwd|token|secret|api_?key|totp|crypt|key_hash)';
        IF cols IS NOT NULL THEN
            EXECUTE format('GRANT SELECT (%s) ON public.%I TO mcp_ro', cols, t.table_name);
        END IF;
    END LOOP;
END $$;
