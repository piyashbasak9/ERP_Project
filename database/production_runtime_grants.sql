\set ON_ERROR_STOP on

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO erp_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO erp_runtime;

\ir savings_runtime_role.sql
