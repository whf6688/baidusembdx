#!/usr/bin/env bash
set -Eeuo pipefail

archive="${1:-}"
release_id="${2:-}"
app_root="/www/baidu-search"
releases_root="${app_root}/releases"
backups_root="${app_root}/backups"
current_link="${app_root}/current"
new_release="${releases_root}/${release_id}"
lock_file="${app_root}/publish.lock"
health_url="http://127.0.0.1:18080/api/v1/health"
old_release=""
backup_file=""
switched=0
workers_stopped=0

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

rollback() {
  local code="$1"
  local line="$2"
  trap - ERR
  echo "Publish failed at line ${line}; restoring the previous application version." >&2

  if [[ -n "$old_release" && -d "$old_release" ]]; then
    if [[ "$switched" == "1" ]]; then
      ln -sfn "$old_release" "$current_link"
      docker compose \
        --env-file "$old_release/deploy/.env.production" \
        -f "$old_release/deploy/docker-compose.production.yml" \
        up -d --remove-orphans || true
    elif [[ "$workers_stopped" == "1" ]]; then
      docker compose \
        --env-file "$old_release/deploy/.env.production" \
        -f "$old_release/deploy/docker-compose.production.yml" \
        up -d worker scheduler || true
    fi
  fi

  [[ -n "$backup_file" ]] && echo "database_backup=${backup_file}" >&2
  exit "$code"
}
trap 'rollback $? $LINENO' ERR

[[ -f "$archive" ]] || fail "Release archive does not exist."
[[ "$release_id" =~ ^[0-9]{8}-[0-9]{6}$ ]] || fail "Invalid release identifier."
[[ -L "$current_link" ]] || fail "Current release link does not exist."

exec 9>"$lock_file"
flock -n 9 || fail "Another publish is already running."

old_release="$(readlink -f "$current_link")"
[[ -d "$old_release" ]] || fail "Current release directory does not exist."
[[ ! -e "$new_release" ]] || fail "Release already exists: ${release_id}"

if tar -tzf "$archive" | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
  fail "Unsafe path found in release archive."
fi

available_kb="$(df -Pk "$app_root" | awk 'NR == 2 {print $4}')"
[[ "$available_kb" -ge 5242880 ]] || fail "Less than 5 GB disk space is available."

mkdir -p "$new_release" "$backups_root"
tar -xzf "$archive" -C "$new_release"

for required in \
  backend/Dockerfile \
  backend/alembic.ini \
  frontend/Dockerfile \
  deploy/docker-compose.production.yml; do
  [[ -f "$new_release/$required" ]] || fail "Missing release file: ${required}"
done

[[ -f "$old_release/deploy/.env.production" ]] || fail "Production environment file is missing."
install -m 600 -o root -g root \
  "$old_release/deploy/.env.production" \
  "$new_release/deploy/.env.production"
sed -i '/^RELEASE_ID=/d' "$new_release/deploy/.env.production"
printf '\nRELEASE_ID=%s\n' "$release_id" >> "$new_release/deploy/.env.production"

printf 'release_id=%s\ncreated_at=%s\nprevious_release=%s\n' \
  "$release_id" "$(date --iso-8601=seconds)" "$old_release" \
  > "$new_release/RELEASE_INFO"

old_compose=(
  docker compose
  --env-file "$old_release/deploy/.env.production"
  -f "$old_release/deploy/docker-compose.production.yml"
)
new_compose=(
  docker compose
  --env-file "$new_release/deploy/.env.production"
  -f "$new_release/deploy/docker-compose.production.yml"
)

backup_file="${backups_root}/pre-release-${release_id}.sql.gz"
"${old_compose[@]}" exec -T postgres \
  pg_dump -U search_app -d baidu_platform | gzip -c > "$backup_file"
chmod 600 "$backup_file"
[[ -s "$backup_file" ]] || fail "Database backup is empty."

"${new_compose[@]}" build api web

"${old_compose[@]}" stop worker scheduler
workers_stopped=1

"${new_compose[@]}" run --rm --no-deps api alembic upgrade head

ln -sfn "$new_release" "$current_link"
switched=1
"${new_compose[@]}" up -d --no-build --remove-orphans

healthy=0
for _ in $(seq 1 60); do
  if curl --fail --silent --show-error --max-time 5 "$health_url" >/dev/null; then
    healthy=1
    break
  fi
  sleep 2
done
[[ "$healthy" == "1" ]] || fail "Application health check did not pass within 120 seconds."

"${new_compose[@]}" ps
switched=0
workers_stopped=0
trap - ERR

mapfile -t old_release_ids < <(
  find "$releases_root" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' \
    | grep -E '^[0-9]{8}-[0-9]{6}$' \
    | sort -r \
    | tail -n +6
)
for old_id in "${old_release_ids[@]}"; do
  old_path="${releases_root}/${old_id}"
  resolved="$(realpath "$old_path")"
  if [[ "$resolved" == "${releases_root}/"* && "$resolved" != "$new_release" ]]; then
    rm -rf -- "$resolved"
    docker image rm "baidu-search-backend:${old_id}" "baidu-search-web:${old_id}" >/dev/null 2>&1 || true
  fi
done

# Do not prune host-wide images: this server also hosts unrelated applications.

echo "release=${new_release}"
echo "previous_release=${old_release}"
echo "database_backup=${backup_file}"
echo "health=ok"
