# Runs once inside `pretix shell` on the Railway container (see
# bin/bootstrap-organizer.sh). Safe to run again: it only adds or overwrites
# the values below.
#
# - Organizer "sk" (S+K Verlag) with the plugins the shop needs
# - Team "Administratoren" with the existing admin user
# - Temporary team "Einrichtung" with an API token for bin/setup-testshop.py
#   (delete that team in pretix after the setup)
# - Organizer-wide defaults that every event inherits: seller data on
#   invoices (from the imprint of skverlag.de), invoice and payment rules,
#   attendee data, legal links. With PRETIX_BOOTSTRAP_EVENT=<slug> the
#   event-level copies pretix makes for a new event are removed (only for
#   events without real orders).
import os

from django_scopes import scopes_disabled
from i18nfield.strings import LazyI18nString

from pretix.base.models import Organizer, Team, User
from pretix.base.plugins import get_all_plugins

WANTED_PLUGINS = {
    "pretix.plugins.banktransfer",
    "pretix.plugins.ticketoutputpdf",
    "pretix.plugins.sendmail",
    "pretix.plugins.statistics",
    "pretix.plugins.reports",
    "pretix_zugferd",
    # Free plugins added on 03.11.2026 (Christoph: "alle aufnehmen"). Available to all
    # events; switched on per event in the backend (Einstellungen → Plugins).
    "pretix_pages",
    "pretix_withdrawal",
    "pretix_passbook",
    "pretix_enablebanking",
    "pretix_event_css_js",
    "prtx_faq",
    "pretix_dbevent",
}

FOOTER = ("Stumpf + Kossendey Verlagsgesellschaft mbH · Rathausstraße 1 · 26188 Edewecht · "
          "Amtsgericht Oldenburg HRB 120057 · Geschäftsführer: Christoph Kossendey · "
          "USt-IdNr. DE117828392 · kundenservice@skverlag.de")

SETTINGS = {
    # Shop
    "locales": ["de"],
    "locale": "de",
    "timezone": "Europe/Berlin",
    "contact_mail": "kundenservice@skverlag.de",
    "imprint_url": LazyI18nString({"de": "https://www.skverlag.de/impressum"}),
    "privacy_url": LazyI18nString({"de": "https://www.skverlag.de/datenschutz"}),
    # Attendee data: names and e-mails per ticket, may be added later by the
    # orderer or the attendee (PRETIX_PLAN.md, answers of 03.11.2026)
    "name_scheme": "title_given_family",
    "attendee_names_asked": True,
    "attendee_names_required": False,
    "attendee_emails_asked": True,
    "attendee_emails_required": False,
    "allow_modifications": "attendee",
    "mail_send_order_placed_attendee": True,
    # Invoice address (required, otherwise the country-based tax rules for
    # streaming tickets never apply)
    "invoice_address_asked": True,
    "invoice_address_required": True,
    "invoice_name_required": True,
    "invoice_address_vatid": True,
    # Leitweg-ID for public authorities; pretix-zugferd puts it into the
    # e-invoice (BuyerReference)
    "invoice_address_custom_field": LazyI18nString({"de": "Leitweg-ID oder Ihre Bestellnummer"}),
    "invoice_address_custom_field_helptext": LazyI18nString({"de": "Nur ausfüllen, wenn Ihre Behörde eine Leitweg-ID für E-Rechnungen vorgibt oder Ihre Bestellnummer auf der Rechnung stehen soll."}),
    # Invoices: seller data from the imprint, issued with the order
    "invoice_generate": "True",
    # Invoice layout with embedded e-invoice (ZUGFeRD, profile XRechnung)
    "invoice_renderer": "modern1_zugferd_xrechnung",
    "invoice_numbers_consecutive": True,
    "invoice_numbers_prefix": "SK-",
    "invoice_address_from_name": "Stumpf + Kossendey Verlagsgesellschaft mbH",
    "invoice_address_from": "Rathausstraße 1",
    "invoice_address_from_zipcode": "26188",
    "invoice_address_from_city": "Edewecht",
    "invoice_address_from_country": "DE",
    "invoice_address_from_vat_id": "DE117828392",
    "invoice_address_from_tax_id": "69/200/02772",
    "invoice_footer_text": LazyI18nString({"de": FOOTER}),
    "invoice_include_expire_date": True,
    "invoice_event_location": True,
    "invoice_show_payments": True,
    # Payment: 14 days, unpaid orders do not expire (authorities often pay
    # late), reminder 3 days before the due date
    "payment_term_days": 14,
    "payment_term_expire_automatically": False,
    "mail_days_order_expire_warning": 3,
    # Bank transfer (bank details are a placeholder until Christoph provides them)
    "payment_banktransfer__enabled": True,
    "payment_banktransfer_bank_details_type": "other",
    "payment_banktransfer_bank_details": LazyI18nString({"de": "Bankverbindung folgt (Testbetrieb)."}),
    "payment_banktransfer_invoice_immediately": True,
}

with scopes_disabled():
    available = {p.module for p in get_all_plugins()}
    print("PLUGINS_MISSING", sorted(WANTED_PLUGINS - available))

    org, created = Organizer.objects.get_or_create(slug="sk", defaults={"name": "S+K Verlag"})
    org.plugins = ",".join(sorted(set(filter(None, (org.plugins or "").split(","))) | (WANTED_PLUGINS & available)))
    org.save(update_fields=["plugins"])
    for key, value in SETTINGS.items():
        org.settings.set(key, value)

    # pretix writes some defaults directly onto every new event (e.g. invoice
    # layout, attendee mail, name scheme). Those copies hide the organizer
    # values above. PRETIX_BOOTSTRAP_EVENT=<slug> removes them for that one
    # event, but only while it has no orders, so changes made later in the
    # backend of a real event are never overwritten.
    event_slug = os.environ.get("PRETIX_BOOTSTRAP_EVENT", "").strip()
    if event_slug:
        event = org.events.get(slug=event_slug)
        if event.orders.filter(testmode=False).exists():
            print("EVENT", event.slug, "hat schon echte Bestellungen, Einstellungen bleiben unverändert")
        else:
            for key in SETTINGS:
                event.settings.delete(key)
            print("EVENT", event.slug, "nutzt die Veranstalter-Einstellungen")

    admin = User.objects.get(email=os.environ["PRETIX_ADMIN_EMAIL"])
    admins, _ = Team.objects.get_or_create(
        organizer=org, name="Administratoren",
        defaults=dict(all_events=True, all_event_permissions=True, all_organizer_permissions=True))
    admins.members.add(admin)

    # Creating events needs organizer permissions; this team is deleted after the setup.
    setup, _ = Team.objects.get_or_create(organizer=org, name="Einrichtung (temporär, nach Setup löschen)")
    setup.all_events = setup.all_event_permissions = setup.all_organizer_permissions = True
    setup.save()
    # Used tokens are referenced by the audit log and cannot be deleted: deactivate them.
    setup.tokens.filter(active=True).update(active=False)
    # PRETIX_BOOTSTRAP_TOKEN=none: only deactivate, no new token (end of setup)
    token = None if os.environ.get("PRETIX_BOOTSTRAP_TOKEN") == "none" else setup.tokens.create(name="setup-testshop")

    print("ORGANIZER", org.slug, "neu" if created else "vorhanden", "| Einstellungen:", len(SETTINGS))
    if token:
        print("SETUP_TOKEN", token.token)
    else:
        print("TOKENS deaktiviert")
