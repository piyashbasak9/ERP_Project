\set ON_ERROR_STOP on
\getenv database_name DB_NAME
\getenv admin_role DB_ADMIN_USER
\getenv owner_role DB_OWNER_USER
\getenv owner_password DB_OWNER_PASSWORD
\getenv runtime_password DB_PASSWORD

SELECT format(
    'CREATE ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'owner_role',
    :'owner_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'owner_role')
\gexec

SELECT format(
    'ALTER ROLE %I LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'owner_role',
    :'owner_password'
)
\gexec

SELECT format(
    'CREATE ROLE erp_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'runtime_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'erp_runtime')
\gexec

SELECT format(
    'ALTER ROLE erp_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
    :'runtime_password'
)
\gexec

SELECT format(
    'REASSIGN OWNED BY %I, erp_runtime TO %I',
    :'admin_role',
    :'owner_role'
)
\gexec

DO $$
DECLARE
    membership RECORD;
BEGIN
    FOR membership IN
        SELECT granted_role.rolname
        FROM pg_auth_members
        JOIN pg_roles AS granted_role ON granted_role.oid = pg_auth_members.roleid
        JOIN pg_roles AS member_role ON member_role.oid = pg_auth_members.member
        WHERE member_role.rolname = 'erp_runtime'
    LOOP
        EXECUTE format('REVOKE %I FROM erp_runtime', membership.rolname);
    END LOOP;
END
$$;

SELECT format('ALTER DATABASE %I OWNER TO %I', :'database_name', :'owner_role')
\gexec
SELECT format('ALTER SCHEMA public OWNER TO %I', :'owner_role')
\gexec

GRANT CONNECT ON DATABASE :"database_name" TO erp_runtime;
GRANT CONNECT ON DATABASE :"database_name" TO :"owner_role";
REVOKE CREATE, TEMPORARY ON DATABASE :"database_name" FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO erp_runtime;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO erp_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO erp_runtime;

ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO erp_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner_role" IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO erp_runtime;
