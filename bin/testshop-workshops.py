"""Makes workshops bookable later, in two ways (decided by Christoph 2026-11-03):

1. In the same order: customers may add or change add-on workshops through
   "Bestellung ändern" (only changes that keep or raise the price), until
   14 days before the event. The one-workshop-per-slot limit still applies.
2. In a separate order (e.g. another cost centre): for each add-on workshop
   a standalone, personalized "Einzelbuchung" product in its own category.
   It shares the quota of the add-on workshop, so the seat count is shared.

Also sets the deadline for attendee data (names, e-mails) to 14 days before
the event (PRETIX_PLAN.md, question 3).

    python3 -I bin/testshop-workshops.py --url https://… --token-file <file> [--event testshop]

Safe to run again: existing standalone products are left as they are.
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
args = parser.parse_args()

TOKEN = open(args.token_file).read().strip()
E = f"{args.url.rstrip('/')}/api/v1/organizers/{args.organizer}/events/{args.event}"
FOURTEEN_DAYS_BEFORE = "RELDATE/14/23:59:59/date_from/"
STANDALONE_CATEGORY = "Workshop zu einem vorhandenen Kongressticket nachbuchen"


def call(method, path, body=None):
    request = urllib.request.Request(f"{E}{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Token {TOKEN}", "Content-Type": "application/json",
                                              "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            text = response.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        sys.exit(f"ABBRUCH: {method} {path} -> {error.code}: {error.read().decode()[:1500]}")


def all_results(path):
    results, page = [], call("GET", path)
    results.extend(page["results"])
    while page.get("next"):
        page = call("GET", page["next"].split(f"/events/{args.event}", 1)[1])
        results.extend(page["results"])
    return results


# --- 1. Later changes in the same order -----------------------------------------
call("PATCH", "/settings/", {
    "change_allow_user_addons": True,
    "change_allow_user_price": "gte",            # only changes that keep or raise the price
    "change_allow_user_until": FOURTEEN_DAYS_BEFORE,
    "last_order_modification_date": FOURTEEN_DAYS_BEFORE,  # names/e-mails until 14 days before
})
print("ok: Kunden können Workshops bis 14 Tage vor Beginn nachträglich zur Bestellung hinzufügen")

# --- 2. Standalone workshops for a separate order --------------------------------
categories = {c["name"].get("de"): c for c in all_results("/categories/")}
addon_category_ids = {c["id"] for c in categories.values() if c["is_addon"]}
items = all_results("/items/")
names = {i["name"].get("de") for i in items}
quotas = all_results("/quotas/")
questions = all_results("/questions/")

if STANDALONE_CATEGORY in categories:
    standalone_category = categories[STANDALONE_CATEGORY]["id"]
else:
    standalone_category = call("POST", "/categories/", {
        "name": {"de": STANDALONE_CATEGORY}, "is_addon": False, "position": 10,
        "description": {"de": "Für Teilnehmende, die schon ein Kongressticket haben, z. B. wenn der Workshop über eine "
                              "andere Kostenstelle abgerechnet wird. Bitte Name der teilnehmenden Person angeben."}})["id"]

order_question = next((q for q in questions if q["identifier"] == "kongress_bestellung"), None)
created = []
already_there = 0
for workshop in sorted((i for i in items if i["category"] in addon_category_ids), key=lambda i: i["name"]["de"]):
    name = f"{workshop['name']['de']} (Einzelbuchung)"
    if name in names:
        already_there += 1
        continue
    standalone = call("POST", "/items/", {
        "name": {"de": name}, "category": standalone_category, "active": True,
        "default_price": workshop["default_price"], "tax_rule": workshop["tax_rule"],
        # pretix only asks for a name per ticket on admission products
        "admission": True, "personalized": True,
        "description": {"de": "Nur zusammen mit einem Kongressticket derselben Person. Plätze werden mit der "
                              "Workshop-Buchung im Kongressticket gemeinsam gezählt."},
    })
    created.append(standalone)
    # Same quota as the add-on workshop: one seat count for both ways of booking
    for quota in quotas:
        if workshop["id"] in quota["items"]:
            call("PATCH", f"/quotas/{quota['id']}/", {"items": quota["items"] + [standalone["id"]]})
            quota["items"].append(standalone["id"])

new_ids = [i["id"] for i in created]
if new_ids:
    # Existing questions (organisation, funktion, efn) also for the standalone workshops
    for question in questions:
        if question["identifier"] in ("organisation", "funktion", "efn"):
            call("PATCH", f"/questions/{question['id']}/", {"items": question["items"] + new_ids})
    # Order number of the congress ticket helps to match the person
    if order_question:
        call("PATCH", f"/questions/{order_question['id']}/", {"items": order_question["items"] + new_ids})
    else:
        call("POST", "/questions/", {
            "question": {"de": "Bestellnummer Ihres Kongresstickets"}, "identifier": "kongress_bestellung",
            "type": "S", "required": False, "items": new_ids, "position": 10, "ask_during_checkin": False,
            "help_text": {"de": "Falls zur Hand (steht in der Bestellbestätigung), damit wir die Buchungen sicher zuordnen."}})

print(f"ok: {len(created) + already_there} Workshop(s) einzeln buchbar ({len(created)} neu angelegt), "
      "gemeinsame Platzzahl mit dem Zusatz-Workshop")
for item in created:
    print("   -", item["name"]["de"])
