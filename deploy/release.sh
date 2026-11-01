#!/usr/bin/env bash
set -euo pipefail
umask 0027

if [[ "$EUID" -ne 0 ]]; then
    printf 'Run deployment as root through the approved deployment path.\n' >&2
    exit 2
fi
if [[ "$#" -ne 2 ]]; then
    printf 'Usage: %s <release-id> <git-checkout>\n' "$0" >&2
    exit 2
fi

release_id=$1
source_dir=$(realpath -- "$2")
if [[ ! "$release_id" =~ ^[A-Za-z0-9._-]+$ ]]; then
    printf 'Invalid release identifier.\n' >&2
    exit 2
fi
if [[ ! -d "$source_dir/.git" && ! -f "$source_dir/.git" ]]; then
    printf 'Source must be a Git checkout.\n' >&2
    exit 2
fi

app_root=/srv/erp
releases_dir="$app_root/releases"
current_link="$app_root/current"
previous_link="$app_root/previous"
release_dir="$releases_dir/$release_id"
temporary_dir="$releases_dir/.incoming-$release_id-$$"
runtime_env=/etc/erp/erp.env
roles_env=/etc/erp/database-roles.env
services_stopped=0
release_switched=0

for file in "$runtime_env" "$roles_env"; do
    if [[ ! -f "$file" || "$(stat -c '%u:%a' "$file")" != "0:600" ]]; then
        printf 'Required root-only environment file is missing or not mode 0600: %s\n' "$file" >&2
        exit 2
    fi
done
if [[ -e "$release_dir" || -e "$temporary_dir" ]]; then
    printf 'Release path already exists; choose a new release identifier.\n' >&2
    exit 2
fi

cleanup() {
    local exit_status=$?
    trap - EXIT
    if [[ -n "${temporary_dir:-}" && -d "$temporary_dir" ]]; then
        rm -rf -- "$temporary_dir"
    fi
    if [[ "$services_stopped" -eq 1 ]]; then
        if [[ "$release_switched" -eq 1 ]]; then
            if [[ -L "$previous_link" ]]; then
                rollback_target=$(readlink -f -- "$previous_link")
                if [[ -d "$rollback_target" && "$rollback_target" == "$releases_dir"/* ]]; then
                    rollback_temp="$app_root/.rollback-cleanup-$$"
                    ln -s -- "$rollback_target" "$rollback_temp"
                    mv -Tf -- "$rollback_temp" "$current_link"
                    release_switched=0
                else
                    printf 'Previous release link is invalid; application services remain stopped.\n' >&2
                    exit_status=1
                    services_stopped=0
                fi
            else
                rm -f -- "$current_link"
                printf 'No previous release exists; application services remain stopped.\n' >&2
                services_stopped=0
            fi
        fi
        if [[ "$services_stopped" -eq 1 && -L "$current_link" ]]; then
            if systemctl restart erp-gunicorn.service erp-celery-worker.service erp-celery-beat.service; then
                services_stopped=0
            else
                printf 'Could not restart application services after deployment failure.\n' >&2
                exit_status=1
            fi
        elif [[ "$services_stopped" -eq 1 ]]; then
            printf 'No current release exists; application services remain stopped.\n' >&2
            services_stopped=0
        fi
    fi
    exit "$exit_status"
}
trap cleanup EXIT

install -d -o root -g erpmedia -m 0750 "$releases_dir"
install -d -o erpapp -g erpmedia -m 0750 "$temporary_dir"
git -C "$source_dir" archive "$release_id" | tar -xf - -C "$temporary_dir"

set -a
# These files are created by the root-only installer and must remain root-owned.
. "$runtime_env"
set +a
runtime_database_name=$DB_NAME
runtime_database_password=$DB_PASSWORD
set -a
. "$roles_env"
set +a

if [[ "$DB_NAME" != "$runtime_database_name" || "$DB_USER" != "erp_runtime" \
    || "$runtime_database_password" != "$DB_PASSWORD" \
    || -z "${DB_OWNER_USER:-}" || -z "${DB_OWNER_PASSWORD:-}" || -z "${DB_PASSWORD:-}" ]]; then
    printf 'Database role configuration is incomplete.\n' >&2
    exit 2
fi

services_stopped=1
systemctl stop erp-gunicorn.service erp-celery-worker.service erp-celery-beat.service
runuser --preserve-environment --user=postgres -- \
    psql --dbname="$DB_NAME" --set=ON_ERROR_STOP=1 \
    --file="$temporary_dir/database/production_roles.sql"

export DB_USER=$DB_OWNER_USER
export DB_PASSWORD=$DB_OWNER_PASSWORD
unset DB_OWNER_USER DB_OWNER_PASSWORD
runuser --preserve-environment --user=erp-migrate -- \
    /srv/erp/venv/bin/python "$temporary_dir/manage.py" check --deploy
runuser --preserve-environment --user=erp-migrate -- \
    /srv/erp/venv/bin/python "$temporary_dir/manage.py" migrate --noinput

runuser --preserve-environment --user=postgres -- \
    psql --dbname="$DB_NAME" --set=ON_ERROR_STOP=1 \
    --file="$temporary_dir/database/production_runtime_grants.sql"

export DB_USER=erp_runtime
export DB_PASSWORD=$runtime_database_password
runuser --preserve-environment --user=erpapp -- \
    /srv/erp/venv/bin/python "$temporary_dir/manage.py" collectstatic --noinput

chown -R root:erpmedia "$temporary_dir"
chmod -R u=rwX,g=rX,o= "$temporary_dir"
mv -- "$temporary_dir" "$release_dir"
temporary_dir=

if [[ -L "$current_link" ]]; then
    current_target=$(readlink -f -- "$current_link")
    previous_temp="$app_root/.previous-$$"
    ln -s -- "$current_target" "$previous_temp"
    mv -Tf -- "$previous_temp" "$previous_link"
fi

current_temp="$app_root/.current-$$"
ln -s -- "$release_dir" "$current_temp"
mv -Tf -- "$current_temp" "$current_link"
release_switched=1

restart_services() {
    systemctl restart erp-gunicorn.service erp-celery-worker.service erp-celery-beat.service
}

if ! restart_services; then
    printf 'Release services failed to start; restoring the previous release when available.\n' >&2
    exit 1
fi
if ! curl --fail --silent --show-error --max-time 10 \
    http://127.0.0.1:8000/health/ >/dev/null; then
    printf 'Release health check failed; restoring the previous release when available.\n' >&2
    exit 1
fi

release_switched=0
services_stopped=0
printf 'Release %s is live.\n' "$release_id"
