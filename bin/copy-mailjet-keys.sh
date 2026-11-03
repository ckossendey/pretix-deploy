#!/usr/bin/env bash
# Copies the Mailjet API keys from the participant app (Railway project
# events.skverlag.de, service web) to the pretix service, so pretix sends mail
# through the same verified Mailjet account. Values are never printed.
#
#   bash bin/copy-mailjet-keys.sh
#
# Reads production variables, so Christoph runs it himself.
set -euo pipefail
unset RAILWAY_API_TOKEN
cd "$(dirname "$0")/.."

EVENTS_PROJECT="events.skverlag.de"
TICKETS_PROJECT="tickets.skverlag.de"
SERVICE="pretix"

project_id() {
  railway list --json | python3 -c "import json,sys; print(next(p['id'] for p in json.load(sys.stdin) if p['name']=='$1'))"
}

events_id=$(project_id "$EVENTS_PROJECT")
tickets_id=$(project_id "$TICKETS_PROJECT")

events_vars=$(railway variable list --project "$events_id" --service web --environment production --kv)
key=$(printf '%s\n' "$events_vars" | sed -n 's/^MAILJET_API_KEY=//p')
secret=$(printf '%s\n' "$events_vars" | sed -n 's/^MAILJET_SECRET_KEY=//p')
unset events_vars
if [ -z "$key" ] || [ -z "$secret" ]; then
  echo "ABBRUCH: Mailjet-Schlüssel im Projekt $EVENTS_PROJECT nicht gefunden" >&2
  exit 1
fi

printf '%s' "$key" | railway variable set PRETIX_MAIL_USER --stdin --project "$tickets_id" --service "$SERVICE" --environment production --skip-deploys >/dev/null
printf '%s' "$secret" | railway variable set PRETIX_MAIL_PASSWORD --stdin --project "$tickets_id" --service "$SERVICE" --environment production >/dev/null
unset key secret
echo "ok: PRETIX_MAIL_USER und PRETIX_MAIL_PASSWORD gesetzt, pretix wird neu gestartet"
