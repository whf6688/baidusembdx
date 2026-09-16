#!/usr/bin/env bash
set -euo pipefail

domain="www.pztxwx.cn"
target="/www/server/panel/vhost/nginx/${domain}.conf"
source_file="/tmp/${domain}.conf.new"
auth_source="/tmp/pztxwx.htpasswd.new"
auth_dir="/www/baidu-search/secrets"
auth_file="${auth_dir}/pztxwx.htpasswd"
cert_script="/tmp/request-pztxwx-cert.py"
cert_dir="/www/server/panel/vhost/letsencrypt/${domain}"
web_root="/www/wwwroot/${domain}"
backup="${target}.bak-$(date +%Y%m%d-%H%M%S)"

cleanup() {
  rm -f "$auth_source"
}
trap cleanup EXIT

for required in "$target" "$source_file" "$auth_source" "$cert_script"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing required file: ${required}" >&2
    exit 1
  fi
done

getent group www >/dev/null
mkdir -p "${web_root}/.well-known/acme-challenge" "$auth_dir"
chmod 750 "$auth_dir"

cp -a "$target" "$backup"

/www/server/panel/pyenv/bin/python "$cert_script"

if [[ ! -s "${cert_dir}/fullchain.pem" || ! -s "${cert_dir}/privkey.pem" ]]; then
  echo "Certificate files were not created." >&2
  exit 1
fi

install -m 640 -o root -g www "$auth_source" "$auth_file"
install -m 644 -o root -g root "$source_file" "$target"

if ! nginx -t; then
  cp -a "$backup" "$target"
  nginx -t
  echo "Nginx validation failed; previous configuration restored." >&2
  exit 1
fi

nginx -s reload
echo "backup=${backup}"
echo "domain=https://${domain}"
