"""Applies the look of skverlag.de to the shop (organizer-wide, every event
inherits it): colours and font from the skverlag.de stylesheet, S+K logo.

    python3 -I bin/design-skverlag.py --url https://… --token-file <file>

Source of the values (www.skverlag.de, CSS custom properties, 03.11.2026):
  --accent #003770 (marine blue), --success #2E7D5B, --danger #B43A2E,
  --surface-2 #f4f6f9, font "Fira Sans"; logo /fileadmin/logos/sk-verlag-logo-ohne.svg
  (converted to assets/skverlag-logo.png). Fira Sans comes from the plugin
  pretix-fontpack-free (requirements.txt).
"""
import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--organizer", default="sk")
parser.add_argument("--token-file", required=True)
parser.add_argument("--event", default="testshop", help="event whose tax labels and product order are tidied up")
args = parser.parse_args()

TOKEN = open(args.token_file).read().strip()
API = f"{args.url.rstrip('/')}/api/v1"
# Logo "Rettungsdienst. Veranstaltungen." (supplied by Christoph, 03.11.2026)
LOGO = Path(__file__).resolve().parent.parent / "assets" / "skverlag-veranstaltungen-logo.png"


def request(method, url, data, content_type, extra_headers=None):
    headers = {"Authorization": f"Token {TOKEN}", "Content-Type": content_type, "Accept": "application/json"}
    headers.update(extra_headers or {})
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method, data=data, headers=headers)) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        sys.exit(f"ABBRUCH: {method} {url} -> {error.code}: {error.read().decode()[:1500]}")


logo = request("POST", f"{API}/upload", LOGO.read_bytes(), "image/png",
               {"Content-Disposition": f'attachment; filename="{LOGO.name}"'})

request("PATCH", f"{API}/organizers/{args.organizer}/settings/", json.dumps({
    "primary_color": "#003770",
    "theme_color_success": "#2E7D5B",
    "theme_color_danger": "#B43A2E",
    "theme_color_background": "#f4f6f9",
    "theme_round_borders": True,
    "primary_font": "Fira Sans",
    "organizer_logo_image": logo["id"],
    "organizer_logo_image_inherit": True,   # events show the organizer logo
}).encode(), "application/json")

print("ok: Design von skverlag.de übernommen (Farben, Schrift Fira Sans, Logo)")

# Customers see the tax rule name next to every price ("inkl. 19% USt …"):
# show just "USt" and keep the long description as internal name.
E = f"{API}/organizers/{args.organizer}/events/{args.event}"
for rule in request("GET", f"{E}/taxrules/", None, "application/json")["results"]:
    long_name = rule["name"].get("de") or ""
    if long_name != "USt":
        request("PATCH", f"{E}/taxrules/{rule['id']}/", json.dumps(
            {"name": {"de": "USt"}, "internal_name": rule.get("internal_name") or long_name}).encode(), "application/json")
# Fixed order of the main tickets
order = {"Kongressticket": 1, "Kombiticket Kongress + Abendessen": 2, "Streaming-Ticket": 3}
for item in request("GET", f"{E}/items/", None, "application/json")["results"]:
    position = order.get(item["name"].get("de"))
    if position and item.get("position") != position:
        request("PATCH", f"{E}/items/{item['id']}/", json.dumps({"position": position}).encode(), "application/json")
print("ok: Steuerhinweis „inkl. 19 % USt“, Reihenfolge Kongressticket, Kombiticket, Streaming")
