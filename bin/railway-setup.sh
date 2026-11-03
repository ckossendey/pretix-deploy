#!/usr/bin/env bash
# One-time setup of the Railway project for the pretix ticket shop.
#
#   bash bin/railway-setup.sh <admin-email>
#
# Creates the project "tickets.skverlag.de" with pretix, Postgres and Redis in
# EU West, the /data volume, all variables and the custom domain, and connects
# the GitHub repo last (that starts the first deploy).
#
# Secrets are never printed:
#   - PRETIX_DJANGO_SECRET and the admin password are generated here.
#   - The Mailjet keys are copied from the events.skverlag.de project.
# The admin password can be looked up in Railway (service pretix, Variables,
# PRETIX_ADMIN_PASSWORD) and should be deleted there after the first login.
#
# The script checks all preconditions before it creates anything. It stops
# at the first error. Do not re-run it after a partial run; fix by hand.
set -euo pipefail
unset RAILWAY_API_TOKEN

PROJECT="tickets.skverlag.de"
DOMAIN="tickets.skverlag.de"
REPO="ckossendey/pretix-deploy"
EVENTS_PROJECT="events.skverlag.de"
SERVICE="pretix"
ADMIN_EMAIL="${1:-}"

step() { printf '\n== %s\n' "$*"; }
fail() { printf '\nABBRUCH: %s\n' "$*" >&2; exit 1; }

json_field() { python3 -c "import json,sys; $1" ; }

# --- Preconditions (nothing is created before this section has passed) ------
step "Voraussetzungen prüfen"
[[ "$ADMIN_EMAIL" == *@*.* ]] || fail "Admin-E-Mail als Argument angeben: bash bin/railway-setup.sh name@skverlag.de"
command -v railway >/dev/null || fail "railway CLI fehlt"
command -v gh >/dev/null || fail "gh CLI fehlt"
railway whoami

visibility=$(gh repo view "$REPO" --json visibility -q .visibility 2>/dev/null || true)
[ "$visibility" = "PUBLIC" ] || fail "GitHub-Repo $REPO fehlt oder ist nicht öffentlich"

projects=$(railway list --json)
if printf '%s' "$projects" | json_field "sys.exit(0 if any(p['name']=='$PROJECT' for p in json.load(sys.stdin)) else 1)"; then
  fail "Railway-Projekt $PROJECT existiert schon"
fi
events_id=$(printf '%s' "$projects" | json_field "print(next(p['id'] for p in json.load(sys.stdin) if p['name']=='$EVENTS_PROJECT'))")
workspace=$(printf '%s' "$projects" | json_field "
w = next(p['workspace'] for p in json.load(sys.stdin) if p['name']=='$EVENTS_PROJECT')
print(w['id'] if isinstance(w, dict) else w)")

events_vars=$(railway variable list --project "$events_id" --service web --environment production --kv)
mailjet_key=$(printf '%s\n' "$events_vars" | sed -n 's/^MAILJET_API_KEY=//p')
mailjet_secret=$(printf '%s\n' "$events_vars" | sed -n 's/^MAILJET_SECRET_KEY=//p')
unset events_vars
[ -n "$mailjet_key" ] && [ -n "$mailjet_secret" ] || fail "Mailjet-Schlüssel im Projekt $EVENTS_PROJECT nicht gefunden"
echo "ok: Repo öffentlich, Projekt noch nicht vorhanden, Mailjet-Schlüssel gefunden"

# --- Create ------------------------------------------------------------------
step "Projekt $PROJECT anlegen"
railway init --name "$PROJECT" --workspace "$workspace"

step "Postgres und Redis anlegen"
railway add --database postgres
railway add --database redis

step "Service $SERVICE anlegen (noch ohne Quelle)"
railway add --service "$SERVICE"

services=$(railway service list --json)
for name in Postgres Redis "$SERVICE"; do
  printf '%s' "$services" | json_field "
data = json.load(sys.stdin)
items = data if isinstance(data, list) else data.get('services', [])
sys.exit(0 if any((s.get('name') if isinstance(s, dict) else s) == '$name' for s in items) else 1)" \
    || fail "Service '$name' nicht gefunden – Namen in Railway prüfen, die Variablen-Verweise erwarten 'Postgres' und 'Redis'"
done

step "Alle Services nach EU West (Amsterdam) legen"
for name in Postgres Redis "$SERVICE"; do
  railway service scale --service "$name" eu-west=1 us-west=0 us-east=0 southeast-asia=0
done

step "Volume /data am Service $SERVICE"
railway volume --service "$SERVICE" add --mount-path /data

step "Variablen setzen"
set_var() { railway variable set "$1" --service "$SERVICE" --skip-deploys >/dev/null; echo "  gesetzt: ${1%%=*}"; }
set_secret() { railway variable set "$1" --stdin --service "$SERVICE" --skip-deploys >/dev/null; echo "  gesetzt: $1 (geheim)"; }

set_var "PORT=80"
set_var "PRETIX_PRETIX_INSTANCE_NAME=S+K Tickets"
set_var "PRETIX_PRETIX_URL=https://$DOMAIN"
set_var "PRETIX_PRETIX_CURRENCY=EUR"
set_var "PRETIX_PRETIX_TRUST_X_FORWARDED_FOR=true"
set_var "PRETIX_PRETIX_TRUST_X_FORWARDED_PROTO=true"
set_var "PRETIX_PRETIX_OBLIGATORY_2FA=true"
set_var "PRETIX_DATABASE_BACKEND=postgresql"
set_var 'PRETIX_DATABASE_NAME=${{Postgres.PGDATABASE}}'
set_var 'PRETIX_DATABASE_USER=${{Postgres.PGUSER}}'
set_var 'PRETIX_DATABASE_PASSWORD=${{Postgres.PGPASSWORD}}'
set_var 'PRETIX_DATABASE_HOST=${{Postgres.PGHOST}}'
set_var 'PRETIX_DATABASE_PORT=${{Postgres.PGPORT}}'
set_var 'PRETIX_REDIS_LOCATION=${{Redis.REDIS_URL}}/0'
set_var "PRETIX_REDIS_SESSIONS=true"
set_var 'PRETIX_CELERY_BROKER=${{Redis.REDIS_URL}}/1'
set_var 'PRETIX_CELERY_BACKEND=${{Redis.REDIS_URL}}/2'
set_var "PRETIX_MAIL_HOST=in-v3.mailjet.com"
set_var "PRETIX_MAIL_PORT=587"
set_var "PRETIX_MAIL_TLS=true"
set_var "PRETIX_MAIL_FROM=kundenservice@skverlag.de"
set_var "PRETIX_ADMIN_EMAIL=$ADMIN_EMAIL"

openssl rand -hex 50 | set_secret PRETIX_DJANGO_SECRET
printf '%s' "$mailjet_key" | set_secret PRETIX_MAIL_USER
printf '%s' "$mailjet_secret" | set_secret PRETIX_MAIL_PASSWORD
unset mailjet_key mailjet_secret
openssl rand -base64 30 | tr -d '/+=\n' | cut -c1-24 | set_secret PRETIX_ADMIN_PASSWORD

step "Domain $DOMAIN (Port 80)"
railway domain "$DOMAIN" --service "$SERVICE" --port 80

step "GitHub-Repo verbinden (startet den ersten Deploy)"
railway service source connect --repo "$REPO" --branch main --service "$SERVICE"

step "Fertig. Noch von Hand:"
cat <<EOF
1. Den oben angezeigten DNS-Eintrag (CNAME) für $DOMAIN bei skverlag.de anlegen.
2. In Railway für die Volumes von Postgres und $SERVICE Backups einschalten
   (täglich, wöchentlich, monatlich), wie bei der Teilnehmer-App.
3. Nach dem ersten Deploy auf https://$DOMAIN/control/ mit $ADMIN_EMAIL anmelden.
   Passwort: Railway → $PROJECT → $SERVICE → Variables → PRETIX_ADMIN_PASSWORD.
   Zwei-Faktor-Anmeldung einrichten, dann PRETIX_ADMIN_PASSWORD in Railway löschen.
EOF
