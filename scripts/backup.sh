#!/bin/sh
set -eu

mkdir -p /backups
while true; do
  now="$(date +%s)"
  today="$(date +%Y-%m-%d)"
  target="$(date -d "${today} 03:00:00" +%s)"
  if [ "$target" -le "$now" ]; then
    target="$((target + 86400))"
  fi
  sleep "$((target - now))"
  stamp="$(date +%Y%m%d)"
  temp="/backups/${stamp}.dump.tmp"
  final="/backups/${stamp}.dump"
  if pg_dump --format=custom --file="$temp"; then
    mv "$temp" "$final"
    count=0
    for backup in $(ls -1t /backups/*.dump); do
      count="$((count + 1))"
      if [ "$count" -gt "${BACKUP_RETENTION_DAYS:-14}" ]; then
        rm -f "$backup"
      fi
    done
  else
    rm -f "$temp"
    echo "PostgreSQL backup failed" >&2
  fi
done
