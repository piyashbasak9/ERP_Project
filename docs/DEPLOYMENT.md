# Deployment Runbook

This runbook deploys the ERP stack with Docker Compose. It contains no production hostname or secret. Keep `.env.production`, TLS private keys, age identities, and backup files outside Git and restrict them to the operator account.

## 1. Prepare the host and secret files

1. Provision a supported Linux host with Docker Engine and the Compose plugin. Restrict SSH and Docker access to named operators; membership in the Docker group is effectively root access.
2. Copy `.env.production.example` to `.env.production` on the host. Populate every required value from the organization's secret manager. Do not copy real values into this repository.
3. Generate a strong Django signing key and independent database bootstrap-owner, migration-owner, and runtime passwords. Do not reuse the bootstrap administrator as `DB_OWNER_USER` or `DB_USER`. Store the bootstrap password in a host file with owner-only read permissions and set `DB_ADMIN_PASSWORD_FILE` to that path.
4. Provide a PostgreSQL server certificate whose SAN matches the internal Compose service name `postgres`, its private key with PostgreSQL-compatible restrictive permissions, and the trusted CA certificate. Set `DB_TLS_CERT_FILE`, `DB_TLS_KEY_FILE`, and `DB_TLS_CA_FILE` to those host file paths. The app uses `verify-full`.
5. Provide an HTTPS certificate/key for Nginx as `TLS_CERT_FILE` and `TLS_KEY_FILE`. Configure `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` to the actual deployment values in the host's secret store, not in this repository.
6. Set `PRIVATE_MEDIA_ROOT=/app/private_media`, `DB_SSLMODE=verify-full`, and a recipient-only `AGE_RECIPIENT`. Keep the corresponding age identity offline or in a separate restricted secret store.

## 2. Create the least-privilege database roles

The deployment includes one-shot `db-roles` and `runtime-grants` services. The first uses the bootstrap administrator to create the non-superuser migration owner and DML-only `erp_runtime` role before migrations. The migration service connects as the owner. After migrations, `runtime-grants` applies DML grants and the append-only restrictions in the existing savings/runtime script before any web or worker process starts.

The role service reads `DB_NAME`, `DB_OWNER_USER`, `DB_OWNER_PASSWORD`, and `DB_PASSWORD` from the Compose environment. The bootstrap administrator must have permission to create roles and change database/schema ownership. The owner role runs schema migrations; the web and Celery processes use only `erp_runtime`. `production_runtime_grants.sql` runs after migrations and reuses the append-only restrictions. Run the jobs explicitly on each release so post-migration grants are refreshed:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml up -d postgres redis
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm db-roles
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm migrate
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm runtime-grants
```

These one-shot services use the `deployment` profile and `run --rm`, so privileged credentials are not retained in stopped job-container metadata. PostgreSQL reads its bootstrap password from the mounted Compose secret file. The app and migration services receive only their respective runtime or owner credentials.

Verify the runtime role is not a member of the owner role and is neither superuser nor database owner.

## 3. Deploy and smoke-test

1. Obtain the reviewed image from the approved registry and set `ERP_IMAGE` to its immutable tag or digest.
2. Run the stack. Compose waits for PostgreSQL and Redis health and starts Gunicorn, Celery worker, Celery beat, and Nginx after the role, migration and runtime-grant jobs have completed.

   ```sh
   docker compose --env-file .env.production -f docker-compose.prod.yml up -d --wait
   ```

3. Verify `docker compose ... ps` reports healthy services, `/health/` returns only `{"status":"ok"}`, HTTP redirects to HTTPS, and the login page is available.
4. Verify Nginx serves `/static/`, direct requests to `/_private_media/` return 404, and an authorized Django download has an `X-Accel-Redirect` response which Nginx serves from the internal media location.
5. Review the `check --deploy` output, database TLS configuration, Redis connectivity, MFA enrollment for privileged users, and the audit log before opening access to staff.

## 4. Encrypted backups and restore

Run the backup script from a restricted host or scheduled job with database credentials supplied through environment variables. `pg_dump` and the private media archive are each encrypted to `AGE_RECIPIENT`.

```sh
scripts/backup.sh
```

Copy both encrypted outputs to access-controlled off-host storage and retain the age recipient/identity separately. Back up PostgreSQL WAL separately if point-in-time recovery is required; the included script is a logical full dump, not a WAL archive.

For a restore drill, create an empty scratch database and an empty private-media directory first. Set `CONFIRM_RESTORE=YES`, `DB_NAME` to the scratch database, `DB_OWNER_USER` / `DB_OWNER_PASSWORD`, `AGE_IDENTITY`, `DATABASE_BACKUP`, `MEDIA_BACKUP`, and `PRIVATE_MEDIA_ROOT`, then run:

```sh
scripts/restore.sh
```

The restore script refuses to extract media into a non-empty directory and requires explicit confirmation before running `pg_restore --clean`. Validate row counts, application invariants, and file hashes before promoting restored data. CI runs an encrypted backup/restore round-trip against two disposable PostgreSQL databases.

## 5. Rollback

1. Stop promotion and preserve the failed image tag, deployment logs, request IDs, and database migration output.
2. Restore the previous immutable `ERP_IMAGE` value and redeploy the prior web/worker/beat image.
3. Do not reverse database migrations automatically. Confirm backward compatibility first; if data restoration is required, restore the pre-deployment encrypted dump and matching private-media archive into isolated empty targets, validate them, then coordinate a controlled cutover.
4. Re-run health, login, permission, MFA, and representative financial read-only checks before resuming writes.
5. Record the cause, affected migrations/data, rollback time, and follow-up actions in the incident record.

Take and verify a restorable backup before any migration that changes persisted data. Prefer forward-compatible expand/migrate/contract changes so the previous application image can run during rollback.

## 6. Secret and certificate rotation

1. Create a replacement secret in the secret manager without exposing it in command arguments, logs, or this repository.
2. For database credentials, update the role password through a restricted administrative session, update the host's `.env.production`, recreate application/worker/beat services, verify database connections, then revoke the old credential.
3. Rotate TLS certificates with overlapping CA trust: deploy the new CA to clients first, then the new PostgreSQL server certificate, then remove the old CA after verification. Reload Nginx only after its replacement certificate/key pair is present and validated.
4. Rotate `DJANGO_SECRET_KEY` only with a coordinated restart; existing signed sessions and password-reset links will no longer validate. Require users to sign in again and confirm that privileged accounts still complete MFA.
5. Replace the age recipient for new backups. Retain the prior identity in protected escrow for the full retention period of backups encrypted to it; test both new and retained backup restores.
6. Update CI/test-environment credentials independently. Record approver, date, systems changed, and verification evidence without recording secret values.

## 7. Emergency MFA recovery

If no administrator can complete MFA, an authorized server operator can reset one account using the Django management command. Run it only from a trusted host/container, identify the operator, and provide a ticket or incident reason:

```sh
docker compose --env-file .env.production -f docker-compose.prod.yml exec web \
  python manage.py reset_user_mfa \
  --username '<account-name>' \
  --operator '<operator-identity>' \
  --reason '<ticket-or-incident-reason>'
```

The command deletes that user's TOTP devices and recovery codes, clears the MFA failure lockout, and writes an immutable `MFAReset` audit event attributed to `server-command:<operator-identity>`. This works for the only superuser and does not create an HTTP reset route. On the next authenticated request, an MFA-required user is sent to enrollment. Verify the audit entry and confirm enrollment with the account owner. Keep server/Compose access restricted because this command can reset any user's MFA.

## 8. Incident checklist

- [ ] Declare an incident owner and preserve relevant logs/backups.
- [ ] Contain access: disable affected accounts or restrict network paths; do not delete evidence.
- [ ] Identify affected services, users, branches, files, transaction records, and time window using request IDs and audit events.
- [ ] Rotate only potentially exposed credentials, certificates, signing keys, and age identities; invalidate affected sessions as appropriate.
- [ ] Verify ledger/audit immutability and reconcile financial balances before restoring writes.
- [ ] Restore from a known-good encrypted backup into an isolated environment before any production recovery.
- [ ] Assess regulatory, contractual, and member-notification obligations with the responsible incident lead.
- [ ] Document timeline, decisions, evidence, notifications, recovery checks, and corrective actions.
- [ ] Review the incident after containment and add regression tests for the root cause.
