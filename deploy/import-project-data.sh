#!/usr/bin/env bash
set -Eeuo pipefail

source_dump="${1:-}"
key_patch="${2:-}"
import_id="${3:-}"
app_root="/www/baidu-search"
current_release="$(readlink -f "${app_root}/current")"
backup_root="${app_root}/backups"
backup_file="${backup_root}/pre-project-data-import-${import_id}.dump"
env_file="${current_release}/deploy/.env.production"
env_backup="${backup_root}/pre-project-data-import-${import_id}.env.production"
health_url="http://127.0.0.1:18080/api/v1/health"
restoring=0

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

compose=(
  docker compose
  --env-file "$env_file"
  -f "$current_release/deploy/docker-compose.production.yml"
)

restore_backup() {
  local code="$1"
  local line="$2"
  trap - ERR
  echo "Project data import failed at line ${line}; restoring online data and configuration." >&2

  if [[ "$restoring" == "1" && -s "$backup_file" ]]; then
    install -m 600 -o root -g root "$env_backup" "$env_file" || true
    "${compose[@]}" exec -T postgres \
      psql -v ON_ERROR_STOP=1 -U search_app -d baidu_platform \
      -c 'DROP SCHEMA IF EXISTS search_marketing CASCADE; DROP SCHEMA IF EXISTS platform_core CASCADE;' || true
    cat "$backup_file" | "${compose[@]}" exec -T postgres \
      pg_restore -U search_app -d baidu_platform --no-owner --exit-on-error || true
  fi
  "${compose[@]}" up -d --remove-orphans || true
  rm -f -- "$key_patch"
  echo "online_backup=${backup_file}" >&2
  exit "$code"
}
trap 'restore_backup $? $LINENO' ERR

[[ -f "$source_dump" ]] || fail "Local project data dump does not exist on the server."
[[ -f "$key_patch" ]] || fail "Token encryption configuration does not exist on the server."
[[ "$import_id" =~ ^[0-9]{8}-[0-9]{6}$ ]] || fail "Invalid import identifier."
[[ -d "$current_release" ]] || fail "Current release directory does not exist."
[[ -f "$env_file" ]] || fail "Production environment file does not exist."

key_line="$(grep -m1 '^PLATFORM_TOKEN_ENCRYPTION_KEY=' "$key_patch" || true)"
[[ -n "$key_line" ]] || fail "Token encryption key is missing."

exec 9>"${app_root}/data-import.lock"
flock -n 9 || fail "Another data import is already running."

available_kb="$(df -Pk "$app_root" | awk 'NR == 2 {print $4}')"
[[ "$available_kb" -ge 4194304 ]] || fail "Less than 4 GB disk space is available."

mkdir -p "$backup_root"
install -m 600 -o root -g root "$env_file" "$env_backup"
"${compose[@]}" exec -T postgres \
  pg_dump -U search_app -d baidu_platform --format=custom --no-owner \
  --schema=search_marketing --schema=platform_core > "$backup_file"
chmod 600 "$backup_file"
[[ -s "$backup_file" ]] || fail "Online project database backup is empty."

"${compose[@]}" stop api worker scheduler
restoring=1

"${compose[@]}" exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U search_app -d baidu_platform \
  -c 'DROP SCHEMA IF EXISTS search_marketing CASCADE; DROP SCHEMA IF EXISTS platform_core CASCADE;'

cat "$source_dump" | "${compose[@]}" exec -T postgres \
  pg_restore -U search_app -d baidu_platform --no-owner --exit-on-error

"${compose[@]}" exec -T postgres \
  psql -v ON_ERROR_STOP=1 -U search_app -d baidu_platform \
  -c 'TRUNCATE platform_core.distributed_locks, platform_core.rate_limit_leases, platform_core.oauth_states;'

sed -i '/^PLATFORM_TOKEN_ENCRYPTION_KEY=/d' "$env_file"
printf '%s\n' "$key_line" >> "$env_file"
chmod 600 "$env_file"

"${compose[@]}" run --rm --no-deps api alembic upgrade head
"${compose[@]}" up -d --no-build --remove-orphans

healthy=0
for _ in $(seq 1 90); do
  if curl --fail --silent --show-error --max-time 5 "$health_url" >/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done
[[ "$healthy" == "1" ]] || fail "Application health check did not pass within 180 seconds."

account_count="$("${compose[@]}" exec -T postgres \
  psql -U search_app -d baidu_platform -At \
  -c 'SELECT count(*) FROM search_marketing.accounts;')"
project_count="$("${compose[@]}" exec -T postgres \
  psql -U search_app -d baidu_platform -At \
  -c 'SELECT count(*) FROM search_marketing.projects;')"
token_count="$("${compose[@]}" exec -T postgres \
  psql -U search_app -d baidu_platform -At \
  -c 'SELECT count(*) FROM platform_core.authorization_tokens;')"

restoring=0
trap - ERR
rm -f -- "$source_dump" "$key_patch"

echo "online_backup=${backup_file}"
echo "environment_backup=${env_backup}"
echo "projects=${project_count}"
echo "accounts=${account_count}"
echo "authorization_tokens=${token_count}"
echo "health=ok"
