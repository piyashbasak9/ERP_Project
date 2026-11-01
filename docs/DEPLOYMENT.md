# Ubuntu Linux Deployment Runbook

This runbook deploys the ERP application directly on an Ubuntu 24.04 LTS server.
It uses systemd, Gunicorn, Nginx, PostgreSQL, Redis and versioned release
directories. No production hostname, credential, or secret is included here.

## 1. Prepare the server

Use a dedicated server and named operator accounts. Permit only TCP ports 80 and
443 from the public network. Keep administrative access on the provider console
or a separately controlled management network. PostgreSQL and Redis must listen
on loopback only; do not expose ports 5432 or 6379.

Install the operating-system packages:

```sh
sudo apt update
sudo apt install --yes \
  age build-essential certbot curl git nginx postgresql postgresql-client \
  python3.12 python3.12-venv python3.12-dev redis-server \
  libcairo2 libgdk-pixbuf-2.0-0 libpango-1.0-0 shared-mime-info
```

Create the service identities and directories. The `erpmedia` group allows
Gunicorn to write private uploads and Nginx to read them through the internal
location only:

```sh
sudo groupadd --system erpmedia
sudo useradd --system --home-dir /srv/erp --shell /usr/sbin/nologin \
  --gid erpmedia erpapp
sudo useradd --system --home-dir /var/lib/erp-migrate \
  --shell /usr/sbin/nologin erp-migrate
sudo useradd --system --home-dir /var/lib/erp-backup \
  --shell /usr/sbin/nologin erp-backup
sudo usermod --append --groups erpmedia erp-migrate
sudo usermod --append --groups erpmedia www-data
sudo install -d -o root -g erpmedia -m 0750 /srv/erp/releases
sudo install -d -o erpapp -g erpmedia -m 0750 \
  /srv/erp/private_media /srv/erp/shared/celerybeat
sudo install -d -o erp-backup -g erpmedia -m 0750 /srv/erp/backups
sudo install -d -o root -g root -m 0700 /etc/erp
```

Configure the host firewall with an inbound default-deny policy and allow only
80/tcp and 443/tcp publicly. Configure PostgreSQL with
`listen_addresses = 'localhost'`, TLS enabled, and `hostssl`/SCRAM
authentication for the application database. Configure Redis with
`bind 127.0.0.1 ::1` and `protected-mode yes`. Confirm both listeners are
loopback-only before continuing.

## 2. Install protected environment files

Install the example templates outside the checkout. The installer refuses to
overwrite existing files and creates each destination as `root:root` mode
0600:

```sh
sudo scripts/install-env-templates.sh
sudoedit /etc/erp/erp.env.example
sudoedit /etc/erp/database-roles.env.example
sudoedit /etc/erp/backup.env.example
```

Copy the completed templates to `/etc/erp/erp.env`,
`/etc/erp/database-roles.env`, and `/etc/erp/backup.env`, respectively, and
retain `root:root` ownership with mode 0600. The runtime file contains only the
runtime database credential. The role-provisioning file contains the migration
owner and runtime role credentials; it is read only by the release script.
The backup file contains the runtime database credential and age recipient.
The `DB_PASSWORD` values in the runtime and role-provisioning files must match.
Never load migration-owner credentials into Gunicorn, Celery, or Nginx.

After editing the templates, install the first-use copies without placing
secrets in the repository:

```sh
sudo install -o root -g root -m 0600 /etc/erp/erp.env.example /etc/erp/erp.env
sudo install -o root -g root -m 0600 \
  /etc/erp/database-roles.env.example /etc/erp/database-roles.env
sudo install -o root -g root -m 0600 \
  /etc/erp/backup.env.example /etc/erp/backup.env
```

Set `DJANGO_DEBUG=0`, a unique `DJANGO_SECRET_KEY`, the actual allowed host and
HTTPS CSRF origin, and `DB_SSLMODE=verify-full` in the runtime environment.
Set `DB_SSL_CA_PATH` to the CA file. The PostgreSQL certificate must contain
`localhost` in its SAN when `DB_HOST=localhost`. Use
`PRIVATE_MEDIA_ROOT=/srv/erp/private_media`,
`REDIS_URL=redis://127.0.0.1:6379/0`,
`CELERY_BROKER_URL=redis://127.0.0.1:6379/1`, and
`CELERY_RESULT_BACKEND=redis://127.0.0.1:6379/2`.
Set a real age public recipient only on the server. Keep its private identity
in separate, restricted escrow; do not put it in the runtime environment.

## 3. Create database roles and TLS

Create the application database as the local PostgreSQL administrator. Use the
database name from the protected role file:

```sh
sudo -u postgres createdb --owner=postgres '<database-name>'
```

Populate `/etc/erp/database-roles.env` with the database name, a dedicated
non-superuser `DB_OWNER_USER`, its password, and the `erp_runtime` password.
The release script runs role provisioning as the local PostgreSQL administrator
through peer authentication, so no PostgreSQL administrator password is
stored. It connects to the application database to assign its ownership and
schema privileges. Configure PostgreSQL TLS certificates and `pg_hba.conf`
before the application starts; the Django connection uses certificate
verification and will fail closed.

The migration owner runs Django migrations. Gunicorn and both Celery services
connect as `erp_runtime`, which has DML access but does not own application
tables. `database/production_runtime_grants.sql` reapplies the existing
append-only audit and ledger restrictions after each migration.

## 4. Install Python and systemd/Nginx configuration

Create the shared virtual environment and install the pinned dependencies:

```sh
sudo python3.12 -m venv /srv/erp/venv
sudo /srv/erp/venv/bin/python -m pip install --upgrade pip
sudo /srv/erp/venv/bin/pip install -r requirements.txt
```

Install the checked-in service and logrotate files:

```sh
sudo install -o root -g root -m 0644 deploy/systemd/erp-gunicorn.service \
  /etc/systemd/system/erp-gunicorn.service
sudo install -o root -g root -m 0644 deploy/systemd/erp-celery-worker.service \
  /etc/systemd/system/erp-celery-worker.service
sudo install -o root -g root -m 0644 deploy/systemd/erp-celery-beat.service \
  /etc/systemd/system/erp-celery-beat.service
sudo install -o root -g root -m 0644 deploy/systemd/erp-backup.service \
  /etc/systemd/system/erp-backup.service
sudo install -o root -g root -m 0644 deploy/systemd/erp-backup.timer \
  /etc/systemd/system/erp-backup.timer
sudo install -o root -g root -m 0644 deploy/logrotate-erp \
  /etc/logrotate.d/erp
```

Obtain a certificate from the organization's CA or ACME provider. For ACME,
create `/var/www/letsencrypt` and a temporary HTTP-only Nginx site for the
deployment DNS name:

```sh
sudo install -d -o root -g www-data -m 0755 /var/www/letsencrypt
sudo tee /etc/nginx/sites-available/erp-acme >/dev/null <<EOF
server {
    listen 80;
    server_name ${DEPLOYMENT_DOMAIN};
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }
}
EOF
sudo ln -sfn /etc/nginx/sites-available/erp-acme \
  /etc/nginx/sites-enabled/erp-acme
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
sudo certbot certonly --webroot --webroot-path /var/www/letsencrypt \
  --domain "$DEPLOYMENT_DOMAIN" --email "$CERTBOT_EMAIL" \
  --agree-tos --non-interactive
sudo install -d -o root -g root -m 0755 /etc/ssl/erp
sudo ln -sfn "/etc/letsencrypt/live/$DEPLOYMENT_DOMAIN/fullchain.pem" \
  /etc/ssl/erp/fullchain.pem
sudo ln -sfn "/etc/letsencrypt/live/$DEPLOYMENT_DOMAIN/privkey.pem" \
  /etc/ssl/erp/privkey.pem
sudo install -o root -g root -m 0755 deploy/reload-nginx-after-cert-renewal \
  /etc/letsencrypt/renewal-hooks/deploy/erp-reload-nginx
```

Install the full Nginx site as `/etc/nginx/sites-available/erp`:

```sh
sudo install -o root -g root -m 0644 deploy/nginx.conf \
  /etc/nginx/sites-available/erp
sudo ln -sfn /etc/nginx/sites-available/erp /etc/nginx/sites-enabled/erp
```

Change
`server_name _;` to the deployment DNS name, disable the default site, and
verify with `sudo nginx -t`. The site redirects non-challenge HTTP requests to
HTTPS, enables HSTS, limits login and password-reset requests, caps uploads,
serves static files, and exposes private media only through an internal
X-Accel-Redirect location. Replace the temporary `erp-acme` site with the full
site, enable it, and reload Nginx. The renewal hook reloads Nginx after
successful certificate renewals.

Restart Nginx after adding `www-data` to `erpmedia` so worker processes
inherit the group membership needed to read private media.

The systemd units run as `erpapp`, include `NoNewPrivileges=yes`,
`ProtectSystem=strict`, `PrivateTmp=yes`, and restrict writable paths. Enable
the application services after the first release:

```sh
sudo systemctl daemon-reload
sudo systemctl enable nginx postgresql redis-server
sudo systemctl enable erp-gunicorn erp-celery-worker erp-celery-beat
sudo systemctl enable --now erp-backup.timer
```

## 5. First deployment and updates

Deploy from a clean, reviewed Git checkout. The release script writes the
commit into `/srv/erp/releases/<revision>`, runs the deployment check and
migrations with the database owner role, applies runtime grants, collects
static files, and atomically switches `/srv/erp/current`. It stops Gunicorn
and Celery while provisioning roles and migrating, so schedule a brief
maintenance window. It retains the previous release link for rollback.

```sh
sudo deploy/release.sh "$(git rev-parse --short HEAD)" "$PWD"
```

After the switch, the script restarts Gunicorn and Celery and checks
`http://127.0.0.1:8000/health/`. Confirm Nginx HTTPS, login, privileged MFA,
database TLS, static files and authorized private-media downloads before
opening access to users. Direct requests to `/_private_media/` must return 404.

For each update, take and verify an encrypted backup first, then deploy the
reviewed commit using the same release command. Keep database changes
backward-compatible so the previous code can run if rollback is needed. The
release script applies migrations before switching code and does not reverse a
database migration during rollback.

### One-command code rollback

```sh
sudo /srv/erp/current/deploy/rollback.sh
```

This switches the current symlink to the previous version and restarts the
application services. It does not roll back schema changes or restore data.
If the new migration is not backward-compatible, stop writes and use the
restore/cutover procedure instead.

## 6. Encrypted backup and restore

The `erp-backup.timer` runs the existing `scripts/backup.sh` daily. It writes
encrypted PostgreSQL custom dumps and private-media archives to the configured
backup directory. Copy encrypted outputs to access-controlled off-host storage.
The script performs logical full dumps; configure and test PostgreSQL WAL
archiving separately if point-in-time recovery is required.

Check timer and service status:

```sh
systemctl list-timers erp-backup.timer
systemctl status erp-backup.service
journalctl -u erp-backup.service
```

For a restore drill, use a newly created scratch database owned by the
migration role and an empty private-media directory. Set
`CONFIRM_RESTORE=YES`, `DB_NAME` to the scratch database,
`DB_OWNER_USER`/`DB_OWNER_PASSWORD`, `AGE_IDENTITY`, `DATABASE_BACKUP`,
`MEDIA_BACKUP`, and `PRIVATE_MEDIA_ROOT`, then run:

```sh
sudo -E scripts/restore.sh
```

The restore script refuses a non-empty media destination and requires explicit
confirmation before cleaning the database. Verify table counts, ledger and
subledger invariants, and restored file hashes before using restored data.
CI runs the encrypted backup/restore round-trip against scratch PostgreSQL
databases created directly by the runner's PostgreSQL installation.

## 7. Secret rotation

1. Approve and record the rotation without recording secret values.
2. Change the PostgreSQL owner/runtime passwords in a restricted
   `sudo -u postgres psql` session and update the corresponding root-only files.
3. Restart Gunicorn and Celery, then verify health and database connectivity
   before revoking the old credential.
4. Rotate TLS certificates with overlapping CA trust: install the new CA,
   replace the PostgreSQL server certificate, then remove the old CA after
   verification. Validate and reload Nginx after installing its certificate
   and private key.
5. Coordinate Django signing-key rotation; existing signed sessions and
   password-reset links will no longer validate. Require sign-in again and
   verify privileged MFA.
6. Rotate the age recipient for new backups. Retain the old decryption identity
   in protected escrow for the backup retention period, and test restore of
   archives encrypted to both recipients.
7. Record approver, date, systems changed, and verification evidence without
   storing credentials in logs, tickets, or source control.

## 8. Emergency MFA recovery

If no administrator can complete MFA, an authorized server operator can reset
an account through the audited, server-only Django command. Record the operator
and incident/ticket reason. Do not expose this command through a web endpoint.

```sh
sudo -u erpapp env \
  DJANGO_SETTINGS_MODULE=ERP.settings \
  /srv/erp/venv/bin/python /srv/erp/current/manage.py reset_user_mfa \
  --username '<account>' --reason '<incident or ticket reason>'
```

The command records an audit event and invalidates the account's enrolled
device and recovery codes. Verify the audit record, contact the affected user
through the approved channel, and require MFA enrollment at their next login.

## 9. Incident checklist

- [ ] Assign an incident owner and preserve relevant logs, request IDs, and
  backup metadata.
- [ ] Contain the incident by restricting access or stopping affected services;
  preserve evidence before changing the host.
- [ ] Review JSON application logs and audit events without exporting
  credentials, tokens, or national ID values.
- [ ] Rotate affected database, Django, email, TLS, and backup credentials.
- [ ] Assess affected accounts, branches, financial postings, and private files.
- [ ] Restore only into an isolated scratch environment first; verify financial
  invariants and file hashes before any production recovery.
- [ ] Notify stakeholders and regulators as required by the approved response
  plan.
- [ ] Document timeline, impact, decisions, recovery evidence, and follow-up
  actions.
