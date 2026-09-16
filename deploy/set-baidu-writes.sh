#!/usr/bin/env sh
set -eu

ACTION="${1:-enable}"
ROOT="${BAIDU_SEARCH_RELEASE_ROOT:-/www/baidu-search/current}"
ENV_FILE="$ROOT/deploy/.env.production"
BACKUP_DIR="${BAIDU_SEARCH_BACKUP_ROOT:-/www/baidu-search/backups}"

case "$ACTION" in
  enable) VALUE=true ;;
  disable) VALUE=false ;;
  *)
    echo "usage: $0 [enable|disable]" >&2
    exit 2
    ;;
esac

if [ ! -f "$ENV_FILE" ]; then
  echo "production environment file not found: $ENV_FILE" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$BACKUP_DIR/env-before-baidu-writes-$ACTION-$STAMP"
cp "$ENV_FILE" "$BACKUP"
chmod 600 "$BACKUP"

set_flag() {
  key="$1"
  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i "s/^${key}=.*/${key}=${VALUE}/" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$VALUE" >> "$ENV_FILE"
  fi
}

set_flag BAIDU_WRITES_ENABLED
set_flag ACCOUNT_AUTO_ELIMINATION_ENABLED
set_flag CREATIVE_AUTO_REBUILD_ENABLED
chmod 600 "$ENV_FILE"

cd "$ROOT/deploy"
if ! docker compose \
  --env-file .env.production \
  -f docker-compose.production.yml \
  up -d --force-recreate api worker scheduler web; then
  cp "$BACKUP" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  docker compose \
    --env-file .env.production \
    -f docker-compose.production.yml \
    up -d --force-recreate api worker scheduler web
  echo "service restart failed; configuration restored from $BACKUP" >&2
  exit 1
fi

echo "backup=$BACKUP"
grep -E \
  '^(BAIDU_WRITES_ENABLED|ACCOUNT_AUTO_ELIMINATION_ENABLED|CREATIVE_AUTO_REBUILD_ENABLED|HDUOFEN_CAPTURE_ENABLED)=' \
  "$ENV_FILE"
