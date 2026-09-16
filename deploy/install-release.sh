#!/usr/bin/env bash
set -euo pipefail

release="/www/baidu-search/releases/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$release"
mkdir -p /www/baidu-search/data/postgres
mkdir -p /www/baidu-search/data/redis
mkdir -p /www/baidu-search/data/analytics
mkdir -p /www/baidu-search/data/storage
mkdir -p /www/baidu-search/repository
install -d -m 700 /www/baidu-search/secrets/git-sync
tar -xzf /tmp/baidu-search-release.tar.gz -C "$release"
chmod 600 "$release/deploy/.env.production"
ln -sfn "$release" /www/baidu-search/current
echo "$release"
