#!/usr/bin/env bash
# One-time setup of the organizer inside the running pretix on Railway.
#
#   bash bin/bootstrap-organizer.sh <file-for-the-setup-token>
#   bash bin/bootstrap-organizer.sh --no-token      (end of setup: tokens off)
#
# Runs bin/bootstrap_organizer.py in the container (via railway ssh). The
# temporary API token is written to the given file (mode 600) and never
# printed. Needs SSH write access to the container, so Christoph runs it.
set -euo pipefail
unset RAILWAY_API_TOKEN
cd "$(dirname "$0")/.."

TOKEN_FILE="${1:?Pfad für die Token-Datei angeben oder --no-token}"
TOKEN_MODE=new
[ "$TOKEN_FILE" = "--no-token" ] && TOKEN_MODE=none
OUT=$(mktemp)
trap 'rm -f "$OUT"' EXIT

payload=$(base64 < bin/bootstrap_organizer.py | tr -d '\n')
railway ssh --service pretix -- sh -c "echo $payload | base64 -d | PRETIX_BOOTSTRAP_TOKEN=$TOKEN_MODE AUTOMIGRATE=skip /usr/local/bin/railway-entrypoint shell" > "$OUT" 2>&1

grep -E "^(PLUGINS_MISSING|ORGANIZER|EVENT|TOKENS)|Traceback|Error" "$OUT" || true
[ "$TOKEN_MODE" = none ] && exit 0
(umask 077; sed -n 's/^SETUP_TOKEN //p' "$OUT" | tr -d '\r' > "$TOKEN_FILE")
if [ -s "$TOKEN_FILE" ]; then
  echo "ok: Token gespeichert in $TOKEN_FILE"
else
  echo "ABBRUCH: kein Token erzeugt – Ausgabe oben prüfen" >&2
  exit 1
fi
