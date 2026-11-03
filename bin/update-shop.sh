#!/usr/bin/env bash
# Applies the later additions to an already set-up shop with one temporary
# API token (switched off at the end):
#   - workshops bookable later / separately (bin/testshop-workshops.py)
#   - design of skverlag.de (bin/design-skverlag.py)
#
#   bash bin/update-shop.sh https://pretix-production-4731.up.railway.app
#
# Christoph runs it (creating the token needs SSH write access to the container).
set -euo pipefail
unset RAILWAY_API_TOKEN
cd "$(dirname "$0")/.."

URL="${1:?pretix-Adresse angeben}"
TOKEN_FILE=$(mktemp)
trap 'rm -f "$TOKEN_FILE"' EXIT

echo "== Veranstalter-Einstellungen und temporärer Schlüssel"
bash bin/bootstrap-organizer.sh --token-file "$TOKEN_FILE"
status=0
echo "== Workshops nachträglich und einzeln buchbar"
python3 -I bin/testshop-workshops.py --url "$URL" --token-file "$TOKEN_FILE" || status=$?
echo "== Plugins der Testveranstaltung"
python3 -I bin/testshop-plugins.py --url "$URL" --token-file "$TOKEN_FILE" || status=$?
echo "== Design"
python3 -I bin/design-skverlag.py --url "$URL" --token-file "$TOKEN_FILE" || status=$?
echo "== Schlüssel abschalten"
bash bin/bootstrap-organizer.sh | grep -E "^TOKENS" || true
exit "$status"
