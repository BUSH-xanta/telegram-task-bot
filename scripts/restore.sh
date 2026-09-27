#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
  echo "Usage: restore.sh /backups/YYYYMMDD.dump" >&2
  exit 2
fi
pg_restore --clean --if-exists --no-owner --dbname="${PGDATABASE:?}" "$1"
