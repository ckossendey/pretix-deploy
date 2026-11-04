#!/usr/bin/env bash
# Organizer setup inside the running pretix on Railway (via railway ssh).
#
#   bash bin/bootstrap-organizer.sh --token-file <file>   organizer + settings, new temporary API token
#   bash bin/bootstrap-organizer.sh --event <slug>[,<slug>…]  organizer settings onto new events, tokens off
#
# Runs bin/bootstrap_organizer.py in the container. The temporary API token
# is written to the given file (mode 600) and never printed. Needs SSH write
# access to the container, so Christoph runs it.
set -euo pipefail
unset RAILWAY_API_TOKEN
cd "$(dirname "$0")/.."

TOKEN_FILE=""
EVENT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --token-file) TOKEN_FILE="$2"; shift 2 ;;
    --event) EVENT="$2"; shift 2 ;;
    *) echo "unbekannte Option: $1" >&2; exit 2 ;;
  esac
done
TOKEN_MODE=none
[ -n "$TOKEN_FILE" ] && TOKEN_MODE=new

OUT=$(mktemp)
trap 'rm -f "$OUT"' EXIT
show_output() { sed 's/^SETUP_TOKEN .*/SETUP_TOKEN (entfernt)/' "$OUT"; }

payload=$(base64 < bin/bootstrap_organizer.py | tr -d '\n')
if ! railway ssh --service pretix -- sh -c "echo $payload | base64 -d | PRETIX_BOOTSTRAP_TOKEN=$TOKEN_MODE PRETIX_BOOTSTRAP_EVENT=$EVENT AUTOMIGRATE=skip /usr/local/bin/railway-entrypoint shell" > "$OUT" 2>&1; then
  echo "ABBRUCH: Einrichtung im Container fehlgeschlagen, Ausgabe:" >&2
  show_output >&2
  exit 1
fi
if grep -q "Traceback" "$OUT"; then
  echo "ABBRUCH: Fehler im Einrichtungsskript, Ausgabe:" >&2
  show_output >&2
  exit 1
fi

grep -E "^(PLUGINS_MISSING|ORGANIZER|EVENT|TOKENS)" "$OUT" || true
[ "$TOKEN_MODE" = none ] && exit 0
(umask 077; sed -n 's/^SETUP_TOKEN //p' "$OUT" | tr -d '\r' > "$TOKEN_FILE")
if [ -s "$TOKEN_FILE" ]; then
  echo "ok: temporärer API-Schlüssel gespeichert (wird am Ende abgeschaltet)"
else
  echo "ABBRUCH: kein Schlüssel erzeugt, Ausgabe:" >&2
  show_output >&2
  exit 1
fi
