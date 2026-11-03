"""Creates a test event in pretix through the REST API so the shop can be
tried end to end: ticket with Behörde/Industrie prices, workshops as add-ons
(one per time slot), combo ticket with dinner, streaming ticket with its own
tax rule, questions organisation/funktion/efn. The event runs in test mode,
orders are marked as test orders and get TEST- invoice numbers.

    python3 -I bin/setup-testshop.py --url https://… --token-file <file> [--recreate]

Organizer-wide defaults (invoices, bank transfer, attendee data) come from
bin/bootstrap_organizer.py and are inherited by the event.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True, help="pretix base URL, e.g. https://pretix-production-4731.up.railway.app")
parser.add_argument("--organizer", default="sk")
parser.add_argument("--event", default="testshop")
parser.add_argument("--token-file", required=True)
parser.add_argument("--recreate", action="store_true", help="delete the test event first (only events whose slug starts with 'test')")
args = parser.parse_args()

TOKEN = open(args.token_file).read().strip()
BASE = f"{args.url.rstrip('/')}/api/v1/organizers/{args.organizer}"
EVENT = args.event


def call(method, path, body=None, ok_missing=False):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers={
        "Authorization": f"Token {TOKEN}", "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            text = response.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        # pretix answers 403 instead of 404 for an event that does not exist
        if ok_missing and error.code in (403, 404):
            return None
        sys.exit(f"ABBRUCH: {method} {path} -> {error.code}: {error.read().decode()[:1500]}")


if args.recreate:
    if not EVENT.startswith("test"):
        sys.exit("ABBRUCH: --recreate nur für Veranstaltungen, deren Kürzel mit 'test' beginnt")
    if call("GET", f"/events/{EVENT}/", ok_missing=True):
        call("PATCH", f"/events/{EVENT}/", {"live": False})
        call("DELETE", f"/events/{EVENT}/")
        print("alte Testveranstaltung gelöscht")
elif call("GET", f"/events/{EVENT}/", ok_missing=True):
    sys.exit(f"ABBRUCH: Veranstaltung {EVENT} gibt es schon (mit --recreate neu anlegen)")

E = f"/events/{EVENT}"

# --- Event ---------------------------------------------------------------
call("POST", "/events/", {
    "name": {"de": "Testveranstaltung Notfallmedizin 2027"}, "slug": EVENT, "currency": "EUR", "live": False,
    "testmode": True, "date_from": "2027-03-12T09:00:00+01:00", "date_to": "2027-03-13T17:00:00+01:00",
    "timezone": "Europe/Berlin", "location": {"de": "Tagungszentrum Musterstadt"}, "has_subevents": False,
    "plugins": ["pretix.plugins.banktransfer", "pretix.plugins.ticketoutputpdf", "pretix.plugins.sendmail",
                "pretix.plugins.statistics", "pretix.plugins.reports", "pretix_zugferd"],
})

# pretix sets its own name scheme when an event is created. The API rejects
# every value after the first settings call in a worker process (pretix
# 2026.9 builds the choices from a generator, settings.py line 4061), so this
# step may fail: then set "Titel, Vorname, Nachname" once in the backend.
NAME_SCHEME_HINT = None
try:
    request = urllib.request.Request(f"{BASE}{E}/settings/", method="PATCH",
                                     data=json.dumps({"name_scheme": "title_given_family"}).encode(),
                                     headers={"Authorization": f"Token {TOKEN}", "Content-Type": "application/json"})
    urllib.request.urlopen(request).read()
except urllib.error.HTTPError:
    NAME_SCHEME_HINT = ("Namensformat bitte im Backend setzen: Einstellungen → Allgemein → "
                        "„Titel, Vorname, Nachname“ (pretix-API-Fehler, siehe Kommentar im Skript)")

# --- Tax rules (PRETIX_PLAN.md, section 12; to be confirmed by the tax advisor)
on_site = call("POST", f"{E}/taxrules/", {
    "name": {"de": "USt"}, "internal_name": "USt 19 % Präsenz (Leistungsort Veranstaltungsort)",
    "rate": "19.00", "code": "S/standard",
    "price_includes_tax": True, "default": True, "custom_rules": None})["id"]
streaming_tax = call("POST", f"{E}/taxrules/", {
    "name": {"de": "USt"}, "internal_name": "USt Streaming (Leistungsort Kunde)", "rate": "19.00", "code": "S/standard",
    "price_includes_tax": True, "keep_gross_if_rate_changes": False, "custom_rules": [
        {"country": "DE", "address_type": "", "action": "vat"},
        {"country": "EU", "address_type": "business_vat_id", "action": "reverse", "code": "AE",
         "invoice_text": {"de": "Steuerschuldnerschaft des Leistungsempfängers"}},
        {"country": "EU", "address_type": "", "action": "require_approval"},
        {"country": "CH", "address_type": "", "action": "no", "code": "O",
         "invoice_text": {"de": "Im Inland nicht steuerbare Leistung"}},
        {"country": "ZZ", "address_type": "", "action": "no", "code": "O",
         "invoice_text": {"de": "Im Inland nicht steuerbare Leistung"}},
    ]})["id"]

# --- Catalogue ------------------------------------------------------------
tickets = call("POST", f"{E}/categories/", {"name": {"de": "Tickets"}, "position": 1})["id"]
morning = call("POST", f"{E}/categories/", {"name": {"de": "Workshops Vormittag"}, "is_addon": True, "position": 2})["id"]
afternoon = call("POST", f"{E}/categories/", {"name": {"de": "Workshops Nachmittag"}, "is_addon": True, "position": 3})["id"]
extras = call("POST", f"{E}/categories/", {"name": {"de": "Zusatzleistungen"}, "position": 4})["id"]


def item(payload):
    base = {"active": True, "tax_rule": on_site, "admission": False, "personalized": False}
    base.update(payload)
    return call("POST", f"{E}/items/", base)


workshops = {}
for code, title, category in [("V1", "Atemwegsmanagement", morning), ("V2", "Kindernotfall", morning),
                              ("N1", "Traumaversorgung", afternoon), ("N2", "Großschadenslage", afternoon)]:
    workshops[code] = item({"name": {"de": f"Workshop {code}: {title}"}, "category": category, "default_price": "60.00",
                            "description": {"de": "Max. 20 Plätze. Nur zusammen mit einem Kongressticket buchbar."}})
dinner = item({"name": {"de": "Abendessen"}, "category": extras, "default_price": "40.00", "require_bundling": True})
congress = item({
    "name": {"de": "Kongressticket"}, "category": tickets, "position": 1, "default_price": "290.00", "admission": True, "personalized": True,
    "description": {"de": "Zwei Kongresstage inkl. Tagungsunterlagen und Verpflegung in den Pausen."},
    "has_variations": True,
    "variations": [{"value": {"de": "Behörde / Rettungsdienst"}, "default_price": "250.00", "active": True},
                   {"value": {"de": "Industrie"}, "default_price": "350.00", "active": True}],
    "addons": [{"addon_category": morning, "min_count": 0, "max_count": 1, "price_included": False},
               {"addon_category": afternoon, "min_count": 0, "max_count": 1, "price_included": False}],
})
combo = item({
    "name": {"de": "Kombiticket Kongress + Abendessen"}, "category": tickets, "position": 2, "default_price": "330.00",
    "admission": True, "personalized": True,
    "bundles": [{"bundled_item": dinner["id"], "bundled_variation": None, "count": 1, "designated_price": "40.00"}],
    "addons": [{"addon_category": morning, "min_count": 0, "max_count": 1, "price_included": False},
               {"addon_category": afternoon, "min_count": 0, "max_count": 1, "price_included": False}],
})
streaming = item({"name": {"de": "Streaming-Ticket"}, "category": tickets, "position": 3, "default_price": "150.00",
                  "admission": True, "personalized": True, "tax_rule": streaming_tax,
                  "description": {"de": "Live-Stream beider Kongresstage, Zugangsdaten per E-Mail."}})

# --- Quotas -----------------------------------------------------------------
call("POST", f"{E}/quotas/", {"name": "Kongress vor Ort", "size": 300, "items": [congress["id"], combo["id"]],
                              "variations": [v["id"] for v in congress["variations"]]})
call("POST", f"{E}/quotas/", {"name": "Abendessen", "size": 150, "items": [dinner["id"]], "variations": []})
call("POST", f"{E}/quotas/", {"name": "Streaming", "size": None, "items": [streaming["id"]], "variations": []})
for code, workshop in workshops.items():
    call("POST", f"{E}/quotas/", {"name": f"Workshop {code}", "size": 20, "items": [workshop["id"]], "variations": []})

# --- Questions (fixed identifiers = interface to the participant app) --------
personalized = [congress["id"], combo["id"], streaming["id"]]
for position, (identifier, label, help_text) in enumerate([
    ("organisation", "Organisation / Behörde / Klinik", ""),
    ("funktion", "Funktion", "z. B. Notfallsanitäter/in, Notärztin/Notarzt"),
    ("efn", "EFN (Einheitliche Fortbildungsnummer)", "Nur für Ärztinnen und Ärzte, für die Meldung der CME-Punkte."),
], start=1):
    call("POST", f"{E}/questions/", {"question": {"de": label}, "identifier": identifier, "type": "S",
                                     "required": False, "items": personalized, "position": position,
                                     "help_text": {"de": help_text} if help_text else {}, "ask_during_checkin": False})

# --- Go live in test mode -----------------------------------------------------
call("PATCH", E + "/", {"live": True})
shop = f"{args.url.rstrip('/')}/{args.organizer}/{EVENT}/"
print("ok: Testveranstaltung angelegt (Testmodus)")
print("Shop:    ", shop)
print("Backend: ", f"{args.url.rstrip('/')}/control/event/{args.organizer}/{EVENT}/")
if NAME_SCHEME_HINT:
    print("Hinweis:", NAME_SCHEME_HINT)
