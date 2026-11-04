#!/usr/bin/env bash
# Creates the pretix events from the Tickettoaster products in
# data/tickettoaster-products.txt (test mode, sold tickets ignored) and puts
# the test event back into test mode. One temporary API token, switched off
# at the end.
#
#   bash bin/import-tickettoaster.sh https://pretix-production-4731.up.railway.app
#   python3 -I bin/import-tickettoaster.py --dry-run     # preview only, no token needed
#
# Christoph runs it (creating the token needs SSH write access to the container).
set -euo pipefail
unset RAILWAY_API_TOKEN
cd "$(dirname "$0")/.."

URL="${1:?pretix-Adresse angeben}"
TOKEN_FILE=$(mktemp)
CREATED=$(mktemp)
trap 'rm -f "$TOKEN_FILE" "$CREATED"' EXIT

echo "== Temporärer Schlüssel"
bash bin/bootstrap-organizer.sh --token-file "$TOKEN_FILE"
status=0
echo "== Testveranstaltung im Testmodus"
python3 -I bin/testshop-testmode.py --url "$URL" --token-file "$TOKEN_FILE" || status=$?
echo "== Veranstaltungen aus Tickettoaster"
python3 -I bin/import-tickettoaster.py --url "$URL" --token-file "$TOKEN_FILE" --created-file "$CREATED" || status=$?
while read -r slug; do
  [ -n "$slug" ] || continue
  echo "== Workshops nachträglich und einzeln buchbar: $slug"
  python3 -I bin/testshop-workshops.py --url "$URL" --token-file "$TOKEN_FILE" --event "$slug" || status=$?
done < "$CREATED"
echo "== Veranstalter-Einstellungen für die neuen Veranstaltungen, Schlüssel abschalten"
if [ -s "$CREATED" ]; then
  bash bin/bootstrap-organizer.sh --event "$(paste -sd, "$CREATED")"
else
  bash bin/bootstrap-organizer.sh | grep -E "^TOKENS" || true
fi
exit "$status"
