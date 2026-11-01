#!/usr/bin/env bash
set -euo pipefail
umask 077

: "${DB_NAME:?Set DB_NAME}"
: "${DB_USER:?Set DB_USER}"
: "${DB_PASSWORD:?Set DB_PASSWORD}"
: "${AGE_RECIPIENT:?Set AGE_RECIPIENT}"
: "${BACKUP_DIR:?Set BACKUP_DIR}"
: "${PRIVATE_MEDIA_ROOT:?Set PRIVATE_MEDIA_ROOT}"

export PGPASSWORD="$DB_PASSWORD"
export PGSSLMODE="${DB_SSLMODE:-require}"
if [[ -n "${DB_SSL_CA_PATH:-}" ]]; then
    export PGSSLROOTCERT="$DB_SSL_CA_PATH"
fi
mkdir -p "$BACKUP_DIR"
test -d "$PRIVATE_MEDIA_ROOT"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
db_output="$BACKUP_DIR/database-$timestamp.dump.age"
media_output="$BACKUP_DIR/private-media-$timestamp.tar.age"
db_temp=$(mktemp "$BACKUP_DIR/.database-XXXXXX")
media_temp=$(mktemp "$BACKUP_DIR/.media-XXXXXX")
trap 'rm -f "$db_temp" "$media_temp"' EXIT

pg_dump --no-password --format=custom \
    --host="${DB_HOST:-localhost}" --port="${DB_PORT:-5432}" \
    --username="$DB_USER" "$DB_NAME" \
    | age --encrypt --recipient "$AGE_RECIPIENT" --output "$db_temp"
tar --create --file=- --directory="$PRIVATE_MEDIA_ROOT" . \
    | age --encrypt --recipient "$AGE_RECIPIENT" --output "$media_temp"

mv "$db_temp" "$db_output"
mv "$media_temp" "$media_output"
printf 'Encrypted database and private-media backups created.\n'
