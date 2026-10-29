\set ON_ERROR_STOP on

SELECT format(
    'CREATE ROLE %I LOGIN CREATEDB PASSWORD %L',
    :'test_role',
    :'test_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'test_role')
\gexec

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L',
    :'runtime_role',
    :'runtime_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'runtime_role')
\gexec

GRANT :"runtime_role" TO :"test_role";
GRANT CONNECT ON DATABASE erp_test TO :"test_role";
