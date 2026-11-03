#!/usr/bin/env bash
# Sets up the shop on Railway in one go (Christoph runs it, it needs SSH
# write access to the container):
#   1. organizer, teams, organizer-wide settings, temporary API token
#   2. test event through the API (bin/setup-testshop.py)
#   3. organizer settings onto the new event, API tokens deactivated
#
#   bash bin/setup-shop.sh https://pretix-production-4731.up.railway.app [--recreate]
set -euo pipefail
unset RAILWAY_API_TOKEN
cd "$(dirname "$0")/.."

URL="${1:?pretix-Adresse angeben}"
EXTRA="${2:-}"
TOKEN_FILE=$(mktemp)
trap 'rm -f "$TOKEN_FILE"' EXIT

echo "== 1/3 Veranstalter und Grundeinstellungen"
bash bin/bootstrap-organizer.sh "$TOKEN_FILE"
echo "== 2/3 Testveranstaltung"
python3 -I bin/setup-testshop.py --url "$URL" --token-file "$TOKEN_FILE" $EXTRA
echo "== 3/3 Einstellungen auf die Veranstaltung, Token aus"
bash bin/bootstrap-organizer.sh --no-token
