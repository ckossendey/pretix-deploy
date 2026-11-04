"""Makes subscriber and member prices freely selectable in all events
(Christoph, 04.11.2026): products whose name contains "Abonnent" or "Mitglied"
no longer need a voucher code. Guest list and prize draw (free tickets) keep
needing one.

    python3 -I bin/open-member-prices.py --url https://… --token-file <file>
    bash bin/run-with-token.sh bin/open-member-prices.py https://…   # Christoph, with temporary token

Safe to run again: products that are already open are left as they are.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--organizer", default="sk")
parser.add_argument("--token-file", required=True)
args = parser.parse_args()

TOKEN = open(args.token_file).read().strip()
BASE = f"{args.url.rstrip('/')}/api/v1/organizers/{args.organizer}"
MEMBER_PRICE = re.compile(r"abonnent|mitglied", re.IGNORECASE)


def call(method, path, body=None):
    url = path if path.startswith("http") else BASE + path
    request = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Token {TOKEN}", "Content-Type": "application/json",
                                              "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            text = response.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        sys.exit(f"ABBRUCH: {method} {url} -> {error.code}: {error.read().decode()[:1000]}")


def all_results(path):
    page = call("GET", path)
    results = list(page["results"])
    while page.get("next"):
        page = call("GET", page["next"])
        results.extend(page["results"])
    return results


changed = 0
for event in all_results("/events/"):
    for item in all_results(f"/events/{event['slug']}/items/"):
        name = item["name"].get("de", "")
        if not MEMBER_PRICE.search(name) or not (item["require_voucher"] or item["hide_without_voucher"]):
            continue
        call("PATCH", f"/events/{event['slug']}/items/{item['id']}/",
             {"require_voucher": False, "hide_without_voucher": False})
        changed += 1
        print(f"ok: frei wählbar: {event['slug']}: {name}")
print(f"ok: {changed} Sonderpreis(e) für Abonnenten/Mitglieder freigeschaltet")
