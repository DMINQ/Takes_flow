#!/usr/bin/env sh
# Entrypoint shared by api / worker / relay.
#
# Runs DB migrations to head, then execs whatever CMD was given. Set
# RUN_MIGRATIONS=0 to skip (e.g. for the worker/relay when the api already migrates).
set -e

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  echo "[entrypoint] applying migrations…"
  alembic upgrade head
fi

echo "[entrypoint] starting: $*"
exec "$@"
