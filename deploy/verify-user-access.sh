#!/usr/bin/env sh
set -eu

PROJECT_ID="${1:?project id is required}"
BASE_URL="${BAIDU_SEARCH_INTERNAL_URL:-http://127.0.0.1:18080/api/v1}"
USERNAME="${VERIFY_USERNAME:?VERIFY_USERNAME is required}"
PASSWORD="${VERIFY_PASSWORD:?VERIFY_PASSWORD is required}"
COOKIE_FILE="$(mktemp)"
trap 'rm -f "$COOKIE_FILE"' EXIT
LOGIN_PAYLOAD="$(python3 -c 'import json, os; print(json.dumps({"username": os.environ["VERIFY_USERNAME"], "password": os.environ["VERIFY_PASSWORD"]}))')"

curl -fsS -c "$COOKIE_FILE" \
  -H "Content-Type: application/json" \
  --data "$LOGIN_PAYLOAD" \
  "$BASE_URL/auth/login"
echo
curl -fsS -b "$COOKIE_FILE" "$BASE_URL/session"
echo
curl -fsS -b "$COOKIE_FILE" "$BASE_URL/projects/$PROJECT_ID/ad-build-access/me"
echo
