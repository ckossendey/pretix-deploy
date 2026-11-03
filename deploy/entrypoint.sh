#!/bin/bash
# Container entrypoint for pretix on Railway.
#
# Runs as root, but only to give /data to pretixuser: Railway mounts volumes
# owned by root, pretix runs as UID 15371. Everything else runs as pretixuser.
#
#   all (default)  migrate, secure the default admin, then web + worker + cron
#   <anything>     passed to the official `pretix` command (e.g. "cron", "shell")
set -euo pipefail

PRETIX_UID=15371

run_as_pretix() {
  setpriv --reuid="$PRETIX_UID" --regid="$PRETIX_UID" --init-groups env HOME=/pretix "$@"
}

if [ "$(stat -c %u /data)" != "$PRETIX_UID" ]; then
  echo "[pretix-deploy] /data gehört nicht pretixuser, Rechte werden angepasst"
  chown -R pretixuser:pretixuser /data
fi

if [ "${1:-all}" != "all" ]; then
  exec setpriv --reuid="$PRETIX_UID" --regid="$PRETIX_UID" --init-groups env HOME=/pretix /usr/local/bin/pretix "$@"
fi

if [ "${AUTOMIGRATE:-yes}" != "skip" ]; then
  echo "[pretix-deploy] Datenbank-Migrationen"
  run_as_pretix AUTOMIGRATE=skip /usr/local/bin/pretix migrate --noinput
fi

# pretix creates admin@localhost with password "admin" on the first migration.
# Replace it before the web server accepts requests.
run_as_pretix AUTOMIGRATE=skip /usr/local/bin/pretix shell < /usr/local/share/pretix-deploy/secure_default_admin.py

exec setpriv --reuid="$PRETIX_UID" --regid="$PRETIX_UID" --init-groups env HOME=/pretix AUTOMIGRATE=skip /usr/local/bin/pretix all
