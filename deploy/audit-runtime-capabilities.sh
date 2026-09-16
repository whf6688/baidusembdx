#!/usr/bin/env bash
set -euo pipefail

prefix="${1:-baidu-search-prod}"
worker="${prefix}-worker-1"
postgres="${prefix}-postgres-1"
data_root="${2:-/www/baidu-search/data}"

echo RUNTIME
docker exec "$worker" sh -c "env | grep -E '^(HDUOFEN_CAPTURE_ENABLED|DUCKDB_PATH|STORAGE_ROOT)='"
for key in HDUOFEN_USERNAME HDUOFEN_PASSWORD HDUOFEN_SESSION_ENCRYPTION_KEY; do
  if docker exec "$worker" sh -c "env | grep -q '^${key}=.'"; then
    echo "${key}_CONFIGURED=true"
  else
    echo "${key}_CONFIGURED=false"
  fi
done

echo COUNTS
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'projects=' || count(*) FROM search_marketing.projects"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'accounts=' || count(*) FROM search_marketing.accounts"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'materials=' || count(*) FROM search_marketing.materials"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'hduofen_events=' || count(*) FROM search_marketing.hduofen_events"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'hduofen_mappings=' || count(*) FROM search_marketing.hduofen_account_mappings"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'tracking_enabled=' || count(*) FROM search_marketing.project_preferences WHERE key='tracking' AND COALESCE((value->>'enabled')::boolean, false)"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'hduofen_max=' || COALESCE(max(event_at)::text, '') FROM search_marketing.hduofen_events"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'material_versions=' || count(*) FROM search_marketing.material_versions"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'reference_raw_paths=' || count(*) FROM search_marketing.reference_template_versions WHERE raw_data_path IS NOT NULL"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'auth_tokens=' || count(*) FROM platform_core.authorization_tokens"
docker exec "$postgres" psql -U search_app -d baidu_platform -At -c \
  "SELECT 'account_bindings=' || count(*) FROM platform_core.account_bindings"

echo FILES
printf 'storage_files='
find "$data_root/storage" -type f 2>/dev/null | wc -l || true
printf 'hduofen_files='
find "$data_root/storage/hduofen" -type f 2>/dev/null | wc -l || true
printf 'duckdb_files='
find "$data_root/analytics" -maxdepth 1 -type f -name '*.duckdb*' 2>/dev/null | wc -l || true
