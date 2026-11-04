"""Creates pretix events from Tickettoaster products (Christoph, 04.11.2026).

Reads the public product JSON of Tickettoaster and builds one pretix event per
product. Sold tickets are ignored: quotas get the full capacity. Events are
created live in test mode, so they show up in the shop and the widget, but
orders are test orders.

How Tickettoaster variants become pretix products (rules in this order):
  - "netto" or 0 % VAT        skipped: pretix makes net prices itself through the
                              tax rules (reverse charge, Switzerland); tickets for
                              an event on site are 19 % anyway (PRETIX_PLAN.md §12)
  - capacity 0                skipped
  - "… inkl. Workshop N"      no product of its own: ticket + add-on workshop N;
                              its capacity is added to both quotas
  - "Workshop …"              add-on workshop; overlapping time slots form one
                              category (max. one workshop per slot)
  - "Streaming"/"Livestream"  streaming ticket with the streaming tax rule
  - online event              location "Online": every product gets the streaming
                              tax rule (place of supply = customer)
  - "Get-Together"            supporting programme, no ticket of its own
  - Abonnent/Mitglied/Gästeliste/Gewinnspiel
                              own product, only with a voucher code, hidden
                              otherwise; shares the quota of its group
  - "Neu"                     unclear, created inactive
  - everything else           ticket (personalized, admission)

    python3 -I bin/import-tickettoaster.py --dry-run
    python3 -I bin/import-tickettoaster.py --url https://… --token-file <file> [--created-file <file>]

Safe to run again: events whose slug already exists are skipped.
"""
import argparse
import datetime
import json
import re
import sys
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

parser = argparse.ArgumentParser()
parser.add_argument("--url", help="pretix base URL")
parser.add_argument("--organizer", default="sk")
parser.add_argument("--token-file")
parser.add_argument("--products-file", default=str(Path(__file__).resolve().parent.parent / "data/tickettoaster-products.txt"))
parser.add_argument("--created-file", help="writes the slugs of newly created events, one per line")
parser.add_argument("--dry-run", action="store_true", help="only show what would be created")
args = parser.parse_args()
if not args.dry_run and not (args.url and args.token_file):
    parser.error("--url und --token-file angeben (oder --dry-run)")

BERLIN = ZoneInfo("Europe/Berlin")
OUR_MERCHANT = "Verlag Stumpf & Kossendey GmbH"
ASSUMED_END_TIME = datetime.time(17, 0)
PLUGINS = ["pretix.plugins.banktransfer", "pretix.plugins.ticketoutputpdf", "pretix.plugins.sendmail",
           "pretix.plugins.statistics", "pretix.plugins.reports", "pretix_zugferd",
           "pretix_pages", "prtx_faq", "pretix_passbook", "pretix_event_css_js"]
TRAIN_PLUGIN = "pretix_dbevent"  # DB event offer, only for events on site
RESTRICTED = re.compile(r"abonnent|mitglied|gaesteliste|gewinnspiel")
STOPWORDS = {"in", "im", "der", "die", "das", "fuer", "und", "von", "zu", "mit", "am", "an", "beginn", "uhr"}
MONTHS = {m: i for i, m in enumerate(["januar", "februar", "maerz", "april", "mai", "juni", "juli", "august",
                                      "september", "oktober", "november", "dezember"], start=1)}


# --- Text helpers ------------------------------------------------------------------
def clean(text):
    return re.sub(r"\s+", " ", (text or "").replace("None", "")).strip()


def fold(text):
    """Lower case, umlauts spelled out: for comparisons only."""
    text = clean(text).lower()
    for umlaut, spelled in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(umlaut, spelled)
    return text


def without_parentheses(text):
    return clean(re.sub(r"\([^)]*\)", " ", text))


def slug_for(title, start):
    words = re.split(r"[^a-z0-9]+", fold(without_parentheses(title)))
    words = [w for w in words if w and w not in STOPWORDS and not re.fullmatch(r"\d+|20\d\d", w)]
    slug = ""
    for word in words:
        if len(slug) + len(word) + 1 > 42:
            break
        slug = f"{slug}-{word}" if slug else word
    return f"{slug}-{start:%Y-%m}"


def short_name(title, event_title):
    """Product name without the event title in front ('10. Symposium … 2026' -> 'Ticket')."""
    for prefix in (event_title, without_parentheses(event_title)):
        if title.lower().startswith(prefix.lower()):
            rest = title[len(prefix):].strip(" -–:")
            return "Ticket" if re.fullmatch(r"[\d.\s/–-]*", rest) else rest
    return title


def qualifier(title):
    """'… (Mitglieder BVBRW)' -> 'Mitglieder BVBRW', '… - Gewinnspiel' -> 'Gewinnspiel'."""
    match = re.search(r"\(([^()]*)\)\s*$", title)
    if match:
        return match.group(1).strip(), title[:match.start()].strip()
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        return tail.strip(), head.strip()
    return title, title


def time_slot(title):
    """(date, start minute, end minute) of a workshop, from its name; None parts if not found."""
    text = fold(title)
    day = None
    numeric = re.search(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{2,4})", text)
    written = re.search(r"(\d{1,2})\.\s?(" + "|".join(MONTHS) + r")\s(\d{4})", text)
    if numeric:
        d, m, y = (int(x) for x in numeric.groups())
        day = datetime.date(y if y > 100 else 2000 + y, m, d)
        text = text.replace(numeric.group(0), " ")
    elif written:
        day = datetime.date(int(written.group(3)), MONTHS[written.group(2)], int(written.group(1)))
        text = text.replace(written.group(0), " ")
    times = [int(h) * 60 + int(m) for h, m in re.findall(r"(?<![\d.])(\d{1,2})[:.](\d{2})(?!\d)", text)]
    start = times[0] if times else None
    end = times[1] if len(times) > 1 else (start + 90 if start is not None else None)
    return day, start, end


def overlaps(a, b):
    if a[1] is None or b[1] is None:
        return a[1] is None and b[1] is None
    same_day = a[0] is None or b[0] is None or a[0] == b[0]
    return same_day and a[1] < b[2] and b[1] < a[2]


# --- Plan --------------------------------------------------------------------------
def fetch(url):
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "pretix-deploy-import"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def plan_event(url, data):
    title = clean(data["title"])
    location = clean(data["location"])
    online = fold(location) == "online"
    start_day = datetime.date.fromisoformat(data["valid_start_on"])
    end_day = datetime.date.fromisoformat(data["valid_end_on"])
    begin = datetime.time.fromisoformat(data["time_begin"])
    doors = datetime.time.fromisoformat(data["time_open"])
    event = {
        "tt_id": data["id"], "url": url, "title": title, "location": location, "online": online,
        "merchant": clean(data.get("merchant")), "start": datetime.datetime.combine(start_day, begin, BERLIN),
        "admission": datetime.datetime.combine(start_day, doors, BERLIN) if doors < begin else None,
        "end": datetime.datetime.combine(end_day, ASSUMED_END_TIME, BERLIN) if end_day > start_day else None,
        "products": [], "workshops": [], "log": [], "flags": [],
    }
    event["slug"] = slug_for(title, event["start"])
    if event["merchant"] != OUR_MERCHANT:
        event["flags"].append(f"Händler in Tickettoaster ist „{event['merchant']}“, in pretix erscheint S+K als Verkäufer")
    if event["end"]:
        event["flags"].append(f"Ende-Uhrzeit fehlt in Tickettoaster, {ASSUMED_END_TIME:%H:%M} Uhr angenommen")

    combos = []
    for group, entries in data["variants"].items():
        base = None  # first unrestricted product of the group: restricted prices share its quota
        for entry in entries:
            name = clean(entry["title"])
            key = fold(name)
            price = Decimal(entry["total_price"])
            vat = Decimal(entry["vat_rate"])
            cap = None if entry["total_available"] in (None, "None", "") else int(entry["total_available"])

            def log(action):
                event["log"].append((name, f"{price:.2f} €", "–" if cap is None else str(cap), action))

            if re.search(r"\bnetto\b", key) or (vat == 0 and price > 0):
                log("übersprungen: Netto-Variante (pretix rechnet netto über die Steuerregeln)")
                continue
            if cap == 0:
                log("übersprungen: Kontingent 0")
                continue
            if re.search(r"inkl\.?\s*wor?k?shop", key):
                combos.append({"name": name, "price": price, "cap": cap or 0})
                log("kein eigenes Produkt: Ticket + Workshop als Zusatz, Plätze auf beide Kontingente")
                continue
            if re.search(r"\bwor?k?shop\b", key):
                event["workshops"].append({"name": name, "price": price, "cap": cap or 0, "slot": time_slot(name)})
                log("Workshop (Zusatz zum Ticket)")
                continue

            restricted = bool(RESTRICTED.search(key))
            if re.search(r"get[- ]?together", key):
                kind = "extra"
            elif not online and re.search(r"streaming|livestream|\bonline\b", key):
                kind = "streaming"
            else:
                kind = "ticket"
            product = {"name": name, "price": price, "cap": cap, "kind": kind, "restricted": restricted,
                       "active": key != "neu", "quota_of": None, "extra_cap": 0}
            if restricted:
                label, rest = qualifier(name)
                product["display"] = f"{short_name(base['name'] if base else rest, title)} – {label}"
                if base and cap is None:
                    product["quota_of"] = base
                log(f"nur mit Gutschein: {product['display']}" + (" (gleiches Kontingent)" if product["quota_of"] else ""))
            elif not product["active"]:
                product["display"] = name
                event["flags"].append(f"Variante „{name}“ ({price:.2f} €, {cap} Plätze) unklar: inaktiv angelegt")
                log("inaktiv angelegt (unklar)")
            else:
                product["display"] = short_name(name, title)
                duplicate = next((p for p in event["products"] if p["kind"] == kind and not p["restricted"]
                                  and p["price"] == price and p["quota_of"] is None
                                  and (fold(p["name"]).startswith(key) or key.startswith(fold(p["name"])))), None)
                if duplicate:
                    duplicate["extra_cap"] += cap or 0
                    log(f"zusammengelegt mit „{duplicate['display']}“ (Plätze addiert)")
                    continue
                base = base or product
                log({"ticket": "Ticket", "streaming": "Streaming-Ticket", "extra": "Rahmenprogramm"}[kind]
                    + (" (Online-Veranstaltung: Steuerregel Streaming)" if online and kind == "ticket" else ""))
            event["products"].append(product)

    # Combo tickets: capacity goes to the workshop and to the matching ticket
    for combo in combos:
        number = re.search(r"wor?k?shop\s*(\d+)", fold(combo["name"]))
        workshop = number and next((w for w in event["workshops"]
                                    if re.match(rf"wor?k?shop\s*{number.group(1)}\b", fold(w["name"]))), None)
        head = fold(re.split(r"\binkl", combo["name"], 1)[0])
        ticket = next((p for p in event["products"] if p["kind"] == "ticket" and not p["restricted"]
                       and (fold(p["name"]).startswith(head.strip()) or head.strip().startswith(fold(p["name"])))), None)
        if not (workshop and ticket):
            event["flags"].append(f"Kombi „{combo['name']}“ nicht zuordenbar: nicht übernommen")
            continue
        workshop["cap"] += combo["cap"]
        ticket["extra_cap"] += combo["cap"]
        if ticket["price"] + workshop["price"] != combo["price"]:
            event["flags"].append(f"Kombi „{combo['name']}“ kostete {combo['price']:.2f} €, in pretix "
                                  f"{ticket['price'] + workshop['price']:.2f} € (Ticket + Workshop)")

    # Workshops whose time slots overlap form one add-on category (one workshop per slot)
    slots = []
    for workshop in sorted(event["workshops"], key=lambda w: (w["slot"][0] or datetime.date.min, w["slot"][1] or 0)):
        slot = next((s for s in slots if any(overlaps(w["slot"], workshop["slot"]) for w in s)), None)
        if slot is None:
            slots.append([workshop])
        else:
            slot.append(workshop)
    event["slots"] = slots
    if any(w["slot"][1] is None for w in event["workshops"]):
        event["flags"].append("Uhrzeit eines Workshops nicht erkannt: Workshop-Gruppen prüfen")
    return event


def slot_label(slot, single):
    if single:
        return "Workshops"
    day, start, _ = slot[0]["slot"]
    parts = [f"{day:%d.%m.%Y}" if day else None, f"{start // 60:02d}:{start % 60:02d} Uhr" if start is not None else None]
    return "Workshops " + ", ".join(p for p in parts if p)


def print_plan(event):
    kind = "ONLINE" if event["online"] else "vor Ort"
    print(f"\n### {event['title']}  →  {event['slug']}")
    print(f"    {event['start']:%d.%m.%Y %H:%M}" + (f" bis {event['end']:%d.%m.%Y}" if event["end"] else "")
          + f", {event['location']} ({kind}), Tickettoaster-Produkt {event['tt_id']}")
    for name, price, cap, action in event["log"]:
        print(f"    - {name[:70]:70} {price:>10} {cap:>5}  → {action}")
    for slot in event["slots"]:
        names = ", ".join(w["name"][:40] for w in slot)
        print(f"    = {slot_label(slot, len(event['slots']) == 1)}: {len(slot)} Workshop(s), max. 1 je Person ({names} …)")
    for product in event["products"]:
        if product["quota_of"]:
            continue
        shared = [p["display"] for p in event["products"] if p["quota_of"] is product]
        size = "unbegrenzt" if product["cap"] is None else product["cap"] + product["extra_cap"]
        print(f"    # Kontingent {product['display'][:60]}: {size}" + (f" (auch für: {', '.join(shared)})" if shared else ""))
    for workshop in event["workshops"]:
        print(f"    # Kontingent {workshop['name'][:60]}: {workshop['cap']}")
    for flag in event["flags"]:
        print(f"    ! {flag}")


# --- pretix API --------------------------------------------------------------------
def api(method, path, body=None, ok_missing=False):
    base = f"{args.url.rstrip('/')}/api/v1/organizers/{args.organizer}"
    request = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Token {TOKEN}", "Content-Type": "application/json",
                                              "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request) as response:
            text = response.read().decode()
            return json.loads(text) if text else None
    except urllib.error.HTTPError as error:
        if ok_missing and error.code in (403, 404):  # pretix answers 403 for a missing event
            return None
        sys.exit(f"ABBRUCH: {method} {path} -> {error.code}: {error.read().decode()[:1500]}")


def create_event(event):
    E = f"/events/{event['slug']}"
    plugins = PLUGINS + ([] if event["online"] else [TRAIN_PLUGIN])
    body = {
        "name": {"de": event["title"]}, "slug": event["slug"], "currency": "EUR", "live": False, "testmode": True,
        "date_from": event["start"].isoformat(), "timezone": "Europe/Berlin", "has_subevents": False,
        "location": {"de": event["location"]}, "plugins": plugins,
        "comment": f"Aus Tickettoaster übernommen am {datetime.date.today():%d.%m.%Y}: Produkt {event['tt_id']} "
                   f"({event['url']}), Händler {event['merchant']}. Gebuchte Tickets nicht übernommen.",
    }
    if event["end"]:
        body["date_to"] = event["end"].isoformat()
    if event["admission"]:
        body["date_admission"] = event["admission"].isoformat()
    api("POST", "/events/", body)

    # Tax rules as in bin/setup-testshop.py (PRETIX_PLAN.md §12, tax advisor to confirm).
    # pretix needs the first rule to be the default: online events start with streaming.
    rules = {}
    rules["on_site"] = {
        "name": {"de": "USt"}, "internal_name": "USt 19 % Präsenz (Leistungsort Veranstaltungsort)",
        "rate": "19.00", "code": "S/standard", "price_includes_tax": True, "default": not event["online"],
        "custom_rules": None}
    rules["streaming"] = {
        "name": {"de": "USt"}, "internal_name": "USt Streaming (Leistungsort Kunde)", "rate": "19.00",
        "code": "S/standard", "price_includes_tax": True, "keep_gross_if_rate_changes": False,
        "default": event["online"], "custom_rules": [
            {"country": "DE", "address_type": "", "action": "vat"},
            {"country": "EU", "address_type": "business_vat_id", "action": "reverse", "code": "AE",
             "invoice_text": {"de": "Steuerschuldnerschaft des Leistungsempfängers"}},
            {"country": "EU", "address_type": "", "action": "require_approval"},
            {"country": "CH", "address_type": "", "action": "no", "code": "O",
             "invoice_text": {"de": "Im Inland nicht steuerbare Leistung"}},
            {"country": "ZZ", "address_type": "", "action": "no", "code": "O",
             "invoice_text": {"de": "Im Inland nicht steuerbare Leistung"}},
        ]}
    order = ["streaming", "on_site"] if event["online"] else ["on_site", "streaming"]
    tax_ids = {name: api("POST", f"{E}/taxrules/", rules[name])["id"] for name in order}

    def tax_for(kind):
        return tax_ids["streaming"] if event["online"] or kind == "streaming" else tax_ids["on_site"]

    categories = {}

    def category(name, position, addon=False):
        if name not in categories:
            categories[name] = api("POST", f"{E}/categories/", {"name": {"de": name}, "position": position,
                                                                  "is_addon": addon})["id"]
        return categories[name]

    # Workshops first: tickets need the add-on categories
    addons = []
    for position, slot in enumerate(event["slots"], start=10):
        addon_category = category(slot_label(slot, len(event["slots"]) == 1), position, addon=True)
        addons.append({"addon_category": addon_category, "min_count": 0, "max_count": 1, "price_included": False})
        for workshop in slot:
            workshop["id"] = api("POST", f"{E}/items/", {
                "name": {"de": workshop["name"]}, "category": addon_category, "default_price": f"{workshop['price']:.2f}",
                "tax_rule": tax_for("workshop"), "active": True, "admission": False, "personalized": False,
                "description": {"de": "Nur zusammen mit einem Ticket buchbar."}})["id"]
            api("POST", f"{E}/quotas/", {"name": workshop["name"][:190], "size": workshop["cap"],
                                         "items": [workshop["id"]], "variations": []})

    titles = {"ticket": ("Tickets", 1), "streaming": ("Streaming", 2), "extra": ("Rahmenprogramm", 3)}
    personalized = []
    for position, product in enumerate(event["products"], start=1):
        is_ticket = product["kind"] in ("ticket", "streaming")
        body = {
            "name": {"de": product["display"]}, "category": category(*titles[product["kind"]]),
            "position": position, "default_price": f"{product['price']:.2f}", "tax_rule": tax_for(product["kind"]),
            "active": product["active"], "admission": is_ticket, "personalized": is_ticket,
        }
        if product["restricted"]:
            body.update(require_voucher=True, hide_without_voucher=True)
        if product["kind"] == "ticket" and not event["online"] and addons:
            body["addons"] = addons
        product["id"] = api("POST", f"{E}/items/", body)["id"]
        if is_ticket:
            personalized.append(product["id"])

    for product in event["products"]:
        if product["quota_of"]:
            continue
        members = [product["id"]] + [p["id"] for p in event["products"] if p["quota_of"] is product]
        size = None if product["cap"] is None else product["cap"] + product["extra_cap"]
        api("POST", f"{E}/quotas/", {"name": product["display"][:190], "size": size, "items": members, "variations": []})

    # Questions with fixed identifiers (interface to the participant app), as in setup-testshop.py
    for position, (identifier, label, help_text) in enumerate([
        ("organisation", "Organisation / Behörde / Klinik", ""),
        ("funktion", "Funktion", "z. B. Notfallsanitäter/in, Notärztin/Notarzt"),
        ("efn", "EFN (Einheitliche Fortbildungsnummer)", "Nur für Ärztinnen und Ärzte, für die Meldung der CME-Punkte."),
    ], start=1):
        api("POST", f"{E}/questions/", {"question": {"de": label}, "identifier": identifier, "type": "S",
                                        "required": False, "items": personalized, "position": position,
                                        "help_text": {"de": help_text} if help_text else {}, "ask_during_checkin": False})

    api("PATCH", f"{E}/", {"live": True})


# --- Main --------------------------------------------------------------------------
urls = [line.strip() for line in Path(args.products_file).read_text().splitlines()
        if line.strip() and not line.startswith("#")]
events = [plan_event(url, fetch(url)) for url in urls]
slugs = [e["slug"] for e in events]
if len(set(slugs)) != len(slugs):
    sys.exit(f"ABBRUCH: doppelte Kürzel {sorted(s for s in slugs if slugs.count(s) > 1)}")
for event in sorted(events, key=lambda e: e["start"]):
    print_plan(event)
if args.dry_run:
    sys.exit(0)

TOKEN = Path(args.token_file).read_text().strip()
created = []
print()
for event in sorted(events, key=lambda e: e["start"]):
    if api("GET", f"/events/{event['slug']}/", ok_missing=True):
        print(f"schon vorhanden, nicht verändert: {event['slug']}")
        continue
    try:
        create_event(event)
    except SystemExit:
        # An event without orders can be deleted: remove the half-created one, then stop.
        if api("GET", f"/events/{event['slug']}/", ok_missing=True):
            api("PATCH", f"/events/{event['slug']}/", {"live": False})
            api("DELETE", f"/events/{event['slug']}/")
            print(f"halb angelegte Veranstaltung {event['slug']} wieder gelöscht", file=sys.stderr)
        raise
    finally:
        if args.created_file:
            Path(args.created_file).write_text("".join(f"{slug}\n" for slug in created))
    created.append(event["slug"])
    print(f"ok: angelegt (Testmodus): {args.url.rstrip('/')}/{args.organizer}/{event['slug']}/")
if args.created_file:
    Path(args.created_file).write_text("".join(f"{slug}\n" for slug in created))
print(f"ok: {len(created)} Veranstaltung(en) neu angelegt, {len(events) - len(created)} schon vorhanden")
