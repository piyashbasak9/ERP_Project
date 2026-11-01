#!/usr/bin/env bash
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    printf 'Run this installer as root.\n' >&2
    exit 2
fi

repository_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
destination=/etc/erp
install -d -o root -g root -m 0700 "$destination"

templates=(
    "$repository_root/.env.production.example:erp.env.example"
    "$repository_root/deploy/database-roles.env.example:database-roles.env.example"
    "$repository_root/deploy/backup.env.example:backup.env.example"
)

for template in "${templates[@]}"; do
    target_name=${template##*:}
    target_path="$destination/$target_name"
    if [[ -e "$target_path" || -L "$target_path" ]]; then
        printf 'Refusing to overwrite %s\n' "$target_path" >&2
        exit 1
    fi
done

for template in "${templates[@]}"; do
    source_file=${template%%:*}
    target_name=${template##*:}
    target_path="$destination/$target_name"
    install -o root -g root -m 0600 "$source_file" "$target_path"
done

printf 'Environment templates installed in %s with mode 0600.\n' "$destination"
