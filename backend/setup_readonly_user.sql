-- ══════════════════════════════════════════════════════════════════════
-- Horeca Sales Intelligence — Read-Only PostgreSQL User Setup
--
-- Run this script as a PostgreSQL superuser (e.g. postgres) to create
-- a dedicated read-only role for the application.
--
-- Usage:
--   psql -U postgres -d horeca_sales_db -f setup_readonly_user.sql
--
-- After running, update your .env file:
--   DB_READONLY_USER=horeca_reader
--   DB_READONLY_PASSWORD=<password_you_set_below>
-- ══════════════════════════════════════════════════════════════════════

-- 1. Create the read-only role (change password as needed)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'horeca_reader') THEN
        CREATE ROLE horeca_reader WITH LOGIN PASSWORD 'horeca_readonly_2026';
        RAISE NOTICE 'Created role: horeca_reader';
    ELSE
        RAISE NOTICE 'Role horeca_reader already exists — skipping creation.';
    END IF;
END
$$;

-- 2. Grant connect privilege on the database
GRANT CONNECT ON DATABASE horeca_sales_db TO horeca_reader;

-- 3. Grant usage on the public schema
GRANT USAGE ON SCHEMA public TO horeca_reader;

-- 4. Grant SELECT on all existing tables
GRANT SELECT ON ALL TABLES IN SCHEMA public TO horeca_reader;

-- 5. Grant SELECT on all existing sequences (needed for some views)
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO horeca_reader;

-- 6. Ensure future tables also get SELECT granted automatically
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO horeca_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO horeca_reader;

-- 7. Explicitly revoke any write privileges (defense-in-depth)
REVOKE INSERT, UPDATE, DELETE, TRUNCATE
    ON ALL TABLES IN SCHEMA public
    FROM horeca_reader;

REVOKE CREATE ON SCHEMA public FROM horeca_reader;

-- 8. Verify the grants
DO $$
DECLARE
    _count INT;
BEGIN
    SELECT COUNT(*) INTO _count
    FROM information_schema.role_table_grants
    WHERE grantee = 'horeca_reader' AND privilege_type = 'SELECT';

    RAISE NOTICE 'horeca_reader has SELECT on % tables/views.', _count;
END
$$;

-- Done! The horeca_reader role can only SELECT from existing and future tables.
