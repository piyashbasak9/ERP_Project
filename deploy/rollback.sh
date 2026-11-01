#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    printf 'Run rollback as root.\n' >&2
    exit 2
fi

app_root=/srv/erp
current_link="$app_root/current"
previous_link="$app_root/previous"
if [[ ! -L "$current_link" || ! -L "$previous_link" ]]; then
    printf 'Both current and previous release links must exist.\n' >&2
    exit 2
fi

previous_target=$(readlink -f -- "$previous_link")
if [[ ! -d "$previous_target" || "$previous_target" != "$app_root"/releases/* ]]; then
    printf 'The previous release link does not point to a valid release.\n' >&2
    exit 2
fi

current_target=$(readlink -f -- "$current_link")
temporary_link="$app_root/.rollback-$$"
ln -s -- "$previous_target" "$temporary_link"
mv -Tf -- "$temporary_link" "$current_link"
ln -sfn -- "$current_target" "$previous_link"

if ! systemctl restart erp-gunicorn.service erp-celery-worker.service erp-celery-beat.service \
    || ! curl --fail --silent --show-error --max-time 10 \
        http://127.0.0.1:8000/health/ >/dev/null; then
    restore_link="$app_root/.rollback-revert-$$"
    ln -s -- "$current_target" "$restore_link"
    mv -Tf -- "$restore_link" "$current_link"
    ln -sfn -- "$previous_target" "$previous_link"
    if ! systemctl restart erp-gunicorn.service erp-celery-worker.service erp-celery-beat.service; then
        printf 'Rollback health check failed and the prior services could not be restarted.\n' >&2
        exit 1
    fi
    printf 'Rollback health check failed; the prior release was restored.\n' >&2
    exit 1
fi
printf 'Rolled back to %s.\n' "$previous_target"
