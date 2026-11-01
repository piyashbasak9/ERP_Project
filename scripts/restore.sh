#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${CONFIRM_RESTORE:?Set CONFIRM_RESTORE=YES after validating the target}"
: "${DB_NAME:?Set DB_NAME}"
: "${DB_OWNER_USER:?Set DB_OWNER_USER}"
: "${DB_OWNER_PASSWORD:?Set DB_OWNER_PASSWORD}"
: "${AGE_IDENTITY:?Set AGE_IDENTITY}"
: "${DATABASE_BACKUP:?Set DATABASE_BACKUP}"
: "${MEDIA_BACKUP:?Set MEDIA_BACKUP}"
: "${PRIVATE_MEDIA_ROOT:?Set PRIVATE_MEDIA_ROOT to an empty directory}"

if [[ "$CONFIRM_RESTORE" != "YES" ]]; then
    printf 'Refusing restore without CONFIRM_RESTORE=YES.\n' >&2
    exit 2
fi
if [[ ! -d "$PRIVATE_MEDIA_ROOT" || -n "$(find "$PRIVATE_MEDIA_ROOT" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    printf 'PRIVATE_MEDIA_ROOT must exist and be empty.\n' >&2
    exit 2
fi

export PGPASSWORD="$DB_OWNER_PASSWORD"
export PGSSLMODE="${DB_SSLMODE:-require}"
if [[ -n "${DB_SSL_CA_PATH:-}" ]]; then
    export PGSSLROOTCERT="$DB_SSL_CA_PATH"
fi
age --decrypt --identity "$AGE_IDENTITY" "$DATABASE_BACKUP" \
    | pg_restore --no-password --clean --if-exists --no-owner --single-transaction \
        --role="$DB_OWNER_USER" --host="${DB_HOST:-localhost}" \
        --port="${DB_PORT:-5432}" --username="$DB_OWNER_USER" --dbname="$DB_NAME"
age --decrypt --identity "$AGE_IDENTITY" "$MEDIA_BACKUP" \
    | tar --extract --file=- --directory="$PRIVATE_MEDIA_ROOT" --no-same-owner
printf 'Encrypted database and private-media backups restored.\n'
