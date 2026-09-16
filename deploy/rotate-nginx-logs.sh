#!/usr/bin/env bash
set -euo pipefail

stamp="$(date +%Y%m%d-%H%M%S)"
archive="/www/wwwlogs/archive-${stamp}"
mkdir -p "$archive"

count=0
while IFS= read -r -d '' file; do
  mv -- "$file" "$archive/$(basename "$file")"
  count=$((count + 1))
done < <(find /www/wwwlogs -maxdepth 1 -type f -size +500M -print0)

nginx -s reopen
find "$archive" -maxdepth 1 -type f -exec gzip -1 -- {} +

echo "rotated=${count}"
du -sh "$archive"
df -h /
