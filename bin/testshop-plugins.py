"""Switches the free plugins on for the test event (Christoph, 03.11.2026):
Pages, FAQ, Passbook, DB Event Offers, Event CSS & JS. Enable Banking only works on
organizer level and is switched on there by bin/bootstrap_organizer.py.
Withdrawal stays off (see bin/bootstrap_organizer.py, DISABLED_PLUGINS).

    python3 -I bin/testshop-plugins.py --url https://… --token-file <file> [--event testshop]
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

ENABLE = ["pretix_pages", "prtx_faq", "pretix_passbook", "pretix_dbevent", "pretix_event_css_js"]
DISABLE = ["pretix_withdrawal"]

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--organizer", default="sk")
parser.add_argument("--event", default="testshop")
parser.add_argument("--token-file", required=True)
args = parser.parse_args()

TOKEN = open(args.token_file).read().strip()
E = f"{args.url.rstrip('/')}/api/v1/organizers/{args.organizer}/events/{args.event}/"


def call(method, body=None):
    request = urllib.request.Request(E, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        sys.exit(f"ABBRUCH: {method} {E} -> {error.code}: {error.read().decode()[:1000]}")


plugins = set(call("GET")["plugins"])
wanted = sorted((plugins | set(ENABLE)) - set(DISABLE))
result = set(call("PATCH", {"plugins": wanted})["plugins"])
missing = [p for p in ENABLE if p not in result]
print("ok: Plugins an", args.event, "aktiv:", ", ".join(p for p in ENABLE if p in result))
if missing:
    print("Hinweis: nicht aktiviert (nur für den Veranstalter verfügbar?):", ", ".join(missing))
