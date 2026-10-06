-- migrate: admin
-- Least-privilege roles. This migration needs a superuser connection (it creates roles and
-- tightens pg_catalog); every later migration runs as t2s_owner (see text2sql.db.migrations).
--
--   t2s_owner   NOLOGIN. Owns schemas shop and app; migrations SET ROLE to it.
--   t2s_reader  LOGIN.   Runs LLM-generated SQL: SELECT on shop only, minus personal data.
--   t2s_app     LOGIN.   Application state: DML on schema app only.
--
-- No passwords here: `python -m text2sql.db migrate` sets them from READER_DATABASE_URL and
-- APP_DATABASE_URL. Roles are cluster-wide; everything else below is per database.

-- ------------------------------------------------------------------ roles
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't2s_owner') THEN
        CREATE ROLE t2s_owner;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't2s_reader') THEN
        CREATE ROLE t2s_reader;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 't2s_app') THEN
        CREATE ROLE t2s_app;
    END IF;
END
$$;

-- Re-assert attributes every time so the roles converge even if someone changed them.
ALTER ROLE t2s_owner  NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER ROLE t2s_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    NOINHERIT CONNECTION LIMIT 20;
ALTER ROLE t2s_app    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
    NOINHERIT CONNECTION LIMIT 20;

-- The migrator must be able to SET ROLE t2s_owner.
GRANT t2s_owner TO CURRENT_USER;

-- Session defaults for generated SQL. These are defaults, not walls: a session can SET them
-- back, so privileges below are the real enforcement and the guard layer must reject SET.
ALTER ROLE t2s_reader SET default_transaction_read_only = on;
ALTER ROLE t2s_reader SET statement_timeout = '5s';
ALTER ROLE t2s_reader SET idle_in_transaction_session_timeout = '10s';
ALTER ROLE t2s_reader SET lock_timeout = '1s';
ALTER ROLE t2s_reader SET work_mem = '8MB';
ALTER ROLE t2s_reader SET temp_file_limit = '256MB';  -- superuser-only GUC: cannot be raised
ALTER ROLE t2s_reader SET search_path = shop;

-- ------------------------------------------------------------------ database & public schema
DO $$
BEGIN
    -- Nobody gets CONNECT / CREATE / TEMP implicitly.
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO t2s_reader, t2s_app', current_database());
    -- Later migrations run as the owner and may need to create schemas.
    EXECUTE format('GRANT CREATE ON DATABASE %I TO t2s_owner', current_database());
END
$$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON public.schema_migrations FROM PUBLIC;
-- pgvector's types and operators live in public; only the app needs them (embeddings).
GRANT USAGE ON SCHEMA public TO t2s_app;

-- ------------------------------------------------------------------ dangerous functions
-- Server file access and large-object import/export. Most are already superuser-only in
-- PG16; revoke explicitly so the guarantee does not depend on version defaults.
DO $$
DECLARE
    fn regprocedure;
BEGIN
    FOR fn IN
        SELECT p.oid::regprocedure
        FROM pg_proc p
        WHERE p.pronamespace = 'pg_catalog'::regnamespace
          AND p.proname IN (
              'pg_read_file', 'pg_read_binary_file', 'pg_stat_file', 'pg_ls_dir',
              'pg_ls_logdir', 'pg_ls_waldir', 'pg_ls_tmpdir', 'pg_ls_archive_statusdir',
              'pg_current_logfile', 'lo_import', 'lo_export')
    LOOP
        EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, t2s_reader, t2s_app', fn);
    END LOOP;

    -- Cross-database / remote access extensions, if anyone ever installs them.
    FOR fn IN
        SELECT p.oid::regprocedure
        FROM pg_proc p
        JOIN pg_depend d ON d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e'
        JOIN pg_extension e ON e.oid = d.refobjid
        WHERE e.extname IN ('dblink', 'postgres_fdw')
    LOOP
        EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, t2s_reader, t2s_app', fn);
    END LOOP;
END
$$;

-- ------------------------------------------------------------------ schema shop
ALTER SCHEMA shop OWNER TO t2s_owner;
REVOKE ALL ON SCHEMA shop FROM PUBLIC;

DO $$
DECLARE
    obj record;
BEGIN
    FOR obj IN
        SELECT relname FROM pg_class
        WHERE relnamespace = 'shop'::regnamespace AND relkind IN ('r', 'p', 'v', 'm', 'f')
    LOOP
        EXECUTE format('ALTER TABLE shop.%I OWNER TO t2s_owner', obj.relname);
    END LOOP;
    FOR obj IN
        SELECT typname FROM pg_type
        WHERE typnamespace = 'shop'::regnamespace AND typtype = 'd'
    LOOP
        EXECUTE format('ALTER DOMAIN shop.%I OWNER TO t2s_owner', obj.typname);
    END LOOP;
END
$$;

GRANT USAGE ON SCHEMA shop TO t2s_reader;

GRANT SELECT ON
    shop.product_categories,
    shop.products,
    shop.orders,
    shop.order_items,
    shop.order_payments,
    shop.order_reviews,
    shop.geolocations
TO t2s_reader;

-- Personal data. A table-level SELECT would override any column-level REVOKE, so these
-- tables get column-level grants only, and the personal columns are explicitly revoked.
REVOKE SELECT ON shop.customers, shop.sellers FROM t2s_reader;
GRANT SELECT (customer_id, customer_state) ON shop.customers TO t2s_reader;
GRANT SELECT (seller_id, seller_city, seller_state) ON shop.sellers TO t2s_reader;
REVOKE SELECT (customer_unique_id, customer_zip_code_prefix, customer_city)
    ON shop.customers FROM t2s_reader;
REVOKE SELECT (seller_zip_code_prefix) ON shop.sellers FROM t2s_reader;

-- Deliberately NO default privileges for t2s_reader in shop: every new table must be granted
-- explicitly in its migration, after deciding which of its columns are personal data.

-- ------------------------------------------------------------------ schema app
CREATE SCHEMA IF NOT EXISTS app AUTHORIZATION t2s_owner;
ALTER SCHEMA app OWNER TO t2s_owner;
REVOKE ALL ON SCHEMA app FROM PUBLIC;
GRANT USAGE ON SCHEMA app TO t2s_app;

-- Tables created by migrations (as t2s_owner) are automatically read/write for the app.
ALTER DEFAULT PRIVILEGES FOR ROLE t2s_owner IN SCHEMA app
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO t2s_app;
ALTER DEFAULT PRIVILEGES FOR ROLE t2s_owner IN SCHEMA app
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO t2s_app;

COMMENT ON SCHEMA app IS
    'Internal application state (embeddings, cache metadata, user feedback). Not business data; never exposed to generated SQL.';
