#!/usr/bin/env bash
# Runs one of the API setup scripts against the shop on Railway with a
# temporary API token, and switches the token off afterwards.
#
#   bash bin/run-with-token.sh <script.py> <pretix-adresse> [weitere Optionen]
#   bash bin/run-with-token.sh bin/testshop-workshops.py https://pretix-production-4731.up.railway.app
#
# Christoph runs it (creating the token needs SSH write access to the container).
set -euo pipefail
unset RAILWAY_API_TOKEN
cd "$(dirname "$0")/.."

SCRIPT="${1:?Skript angeben}"
URL="${2:?pretix-Adresse angeben}"
shift 2
TOKEN_FILE=$(mktemp)
trap 'rm -f "$TOKEN_FILE"' EXIT

bash bin/bootstrap-organizer.sh --token-file "$TOKEN_FILE" > /dev/null
python3 -I "$SCRIPT" --url "$URL" --token-file "$TOKEN_FILE" "$@" || status=$?
bash bin/bootstrap-organizer.sh | grep -E "^TOKENS" || true
exit "${status:-0}"
