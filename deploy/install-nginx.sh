#!/usr/bin/env bash
set -euo pipefail

target="/www/server/panel/vhost/nginx/baidu-authsem.dyy966.cn.conf"
source_file="/tmp/baidu-authsem.dyy966.cn.conf.new"
backup="${target}.bak-$(date +%Y%m%d-%H%M%S)"
auth_dir="/www/baidu-search/secrets"
auth_file="${auth_dir}/htpasswd"

if [[ -f "$auth_file" ]]; then
  chown root:www "$auth_dir" "$auth_file"
  chmod 750 "$auth_dir"
  chmod 640 "$auth_file"
fi

cp -a "$target" "$backup"
cp "$source_file" "$target"

if ! nginx -t; then
  cp "$backup" "$target"
  nginx -t
  echo "Nginx validation failed; previous configuration restored." >&2
  exit 1
fi

nginx -s reload
echo "backup=${backup}"
