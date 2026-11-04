"""Switches test mode of the test event on (default) or off.

In test mode orders get invoice numbers SK-TEST-… and can be deleted; nothing
counts as a real sale. Also reports orders placed while the shop was live,
because those keep their real invoice numbers.

    python3 -I bin/testshop-testmode.py --url https://… --token-file <file> [--event testshop] [--off]
    bash bin/run-with-token.sh bin/testshop-testmode.py https://…   # Christoph, with temporary token
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--organizer", default="sk")
parser.add_argument("--event", default="testshop")
parser.add_argument("--token-file", required=True)
parser.add_argument("--off", action="store_true", help="switch test mode off (shop sells for real)")
args = parser.parse_args()

TOKEN = open(args.token_file).read().strip()
E = f"{args.url.rstrip('/')}/api/v1/organizers/{args.organizer}/events/{args.event}/"


def call(method, path="", body=None):
    url = E + path
    request = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        sys.exit(f"ABBRUCH: {method} {url} -> {error.code}: {error.read().decode()[:1000]}")


wanted = not args.off
before = call("GET")["testmode"]
result = call("PATCH", body={"testmode": wanted})["testmode"]
if result != wanted:
    sys.exit(f"ABBRUCH: Testmodus ist {result}, erwartet {wanted}")

state = "an (Bestellungen sind Tests, Rechnungen SK-TEST-…)" if result else "AUS (Shop verkauft echt)"
change = "unverändert" if before == result else "umgestellt"
print(f"ok: Testmodus von {args.event} {state} – {change}")

live_orders = call("GET", "orders/?testmode=false&page_size=1")["count"]
if live_orders:
    print(f"Hinweis: {live_orders} echte Bestellung(en) aus der Zeit ohne Testmodus. Sie behalten ihre "
          "Rechnungsnummern; bei Bedarf im Backend stornieren (Rechnungen werden dann storniert, nicht gelöscht).")
else:
    print("ok: keine echten Bestellungen vorhanden")
