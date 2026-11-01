#!/usr/bin/env bash
set -euo pipefail

: "${DB_USER:?Set DB_USER}"
: "${DB_PASSWORD:?Set DB_PASSWORD}"

temp_dir=$(mktemp -d)
source_db="erp_backup_source_${BASHPID}"
target_db="erp_backup_target_${BASHPID}"
source_media="$temp_dir/source-media"
target_media="$temp_dir/target-media"
source_created=0
target_created=0
mkdir -p "$source_media" "$target_media"

cleanup() {
    local exit_status=$?
    trap - EXIT
    if [[ "$target_created" -eq 1 ]] && ! dropdb --no-password \
        --host="${DB_HOST:-localhost}" --port="${DB_PORT:-5432}" \
        --username="$DB_USER" "$target_db"; then
        printf 'Could not remove scratch database %s\n' "$target_db" >&2
        exit_status=1
    fi
    if [[ "$source_created" -eq 1 ]] && ! dropdb --no-password \
        --host="${DB_HOST:-localhost}" --port="${DB_PORT:-5432}" \
        --username="$DB_USER" "$source_db"; then
        printf 'Could not remove scratch database %s\n' "$source_db" >&2
        exit_status=1
    fi
    if ! rm -rf -- "$temp_dir"; then
        printf 'Could not remove temporary backup-test files.\n' >&2
        exit_status=1
    fi
    exit "$exit_status"
}
trap cleanup EXIT

export PGPASSWORD="$DB_PASSWORD"
createdb --no-password --host="${DB_HOST:-localhost}" --port="${DB_PORT:-5432}" \
    --username="$DB_USER" --owner="$DB_USER" "$source_db"
source_created=1
createdb --no-password --host="${DB_HOST:-localhost}" --port="${DB_PORT:-5432}" \
    --username="$DB_USER" --owner="$DB_USER" "$target_db"
target_created=1
psql --no-password --host="${DB_HOST:-localhost}" --port="${DB_PORT:-5432}" \
    --username="$DB_USER" --dbname="$source_db" --set=ON_ERROR_STOP=1 \
    --command="CREATE TABLE restore_probe (value text NOT NULL); INSERT INTO restore_probe VALUES ('restored');"
printf 'private media restore fixture\n' > "$source_media/probe.txt"

age-keygen -o "$temp_dir/identity" >/dev/null 2>&1
recipient=$(age-keygen -y "$temp_dir/identity")

export DB_NAME="$source_db"
export DB_OWNER_USER="$DB_USER"
export DB_OWNER_PASSWORD="$DB_PASSWORD"
export PRIVATE_MEDIA_ROOT="$source_media"
export BACKUP_DIR="$temp_dir/backups"
export AGE_RECIPIENT="$recipient"
scripts/backup.sh
database_backup=$(find "$BACKUP_DIR" -name 'database-*.dump.age' -print -quit)
media_backup=$(find "$BACKUP_DIR" -name 'private-media-*.tar.age' -print -quit)

export DB_NAME="$target_db"
export PRIVATE_MEDIA_ROOT="$target_media"
export AGE_IDENTITY="$temp_dir/identity"
export DATABASE_BACKUP="$database_backup"
export MEDIA_BACKUP="$media_backup"
export CONFIRM_RESTORE=YES
scripts/restore.sh

restored_value=$(psql --no-password --host="${DB_HOST:-localhost}" --port="${DB_PORT:-5432}" \
    --username="$DB_USER" --dbname="$target_db" --tuples-only --no-align \
    --command='SELECT value FROM restore_probe')
test "$restored_value" = "restored"
grep -q 'private media restore fixture' "$target_media/probe.txt"
printf 'Encrypted backup/restore test passed against scratch databases.\n'
