# pretix-deploy – Ticketshop des S+K Verlags

Betriebs-Repo für den Ticketshop **tickets.skverlag.de**. Es enthält kein
eigenes pretix-Programm, nur das Rezept, mit dem das offizielle
[pretix Community](https://github.com/pretix/pretix) (Open Source, keine
Lizenzgebühren) auf Railway läuft: Dockerfile, Plugins, Start-Skripte,
Railway-Einstellungen. Eigene Logik (Teilnehmer, Empfang, Mahnungen) steckt
in der Teilnehmer-App `event-participant-manager`, nicht hier. So bleiben
pretix-Updates einfach.

Plan und Begründung: `event-participant-manager/docs/PRETIX_PLAN.md`.

## Aufbau

| Teil | Was |
|---|---|
| Service `pretix` | ein Container: nginx, Webserver (gunicorn, 3 Prozesse), Hintergrund-Worker (Celery, 2 Prozesse), Cron alle 5 Minuten, alles per supervisord |
| Volume `/data` | Rechnungs-PDFs, Uploads, Logs |
| Postgres | Datenbank (mindestens Version 14) |
| Redis | Cache, Sitzungen, Warteschlange für den Worker |

Unterschiede zum offiziellen Image `pretix/standalone`:

- **Plugin pretix-zugferd** für E-Rechnungen (`requirements.txt`) plus
  **Ghostscript**, ohne das keine E-Rechnung entsteht.
- **Cron ist eingebaut** (`deploy/cron-loop.sh`). Das offizielle Image hat
  keinen, pretix braucht ihn aber für Zahlungserinnerungen, Verfall
  unbezahlter Bestellungen und Aufräumarbeiten.
- **Feste Prozesszahl** (`NUM_WORKERS=3`, `CELERY_CONCURRENCY=2`). Railway
  meldet alle CPUs des Hosts, sonst startet pretix Dutzende Prozesse.
- **Rechte am Volume** (`deploy/entrypoint.sh`): Railway hängt Volumes mit
  root als Besitzer ein. Das Start-Skript übergibt `/data` an den
  pretix-Benutzer und startet pretix dann ohne root.
- **Standard-Admin abgesichert** (`deploy/secure_default_admin.py`): pretix
  legt beim ersten Start `admin@localhost` mit Passwort `admin` an. Beim
  Start wird dieses Konto durch `PRETIX_ADMIN_EMAIL`/`PRETIX_ADMIN_PASSWORD`
  ersetzt. Fehlen die Werte, wird es deaktiviert. Hat das Konto schon ein
  anderes Passwort, passiert nichts.

## Lokal testen

Voraussetzung: Docker Desktop. Auf Apple-Silicon-Macs läuft das Image
emuliert (pretix gibt es nur für Intel/amd64). Der erste Build dauert
deshalb einige Minuten.

```bash
docker compose up --build
```

- Backend: http://localhost:8345/control/, Login `admin@example.com` /
  `local-admin-password` (nur lokal)
- Ausgehende Mails: http://localhost:18025 (Mailpit, nichts geht wirklich raus)
- Alles zurücksetzen: `docker compose down -v`

## Railway

### Einmal-Einrichtung

Die Schritte 1 bis 4 erledigt `bin/railway-setup.sh <admin-e-mail>`. Es
prüft vorher alle Voraussetzungen und am Ende die Region.

1. Railway-Projekt `tickets.skverlag.de` mit den Services `pretix`
   (Quelle: dieses Repo, Branch `main`), `Postgres` und `Redis`, alle in der
   Region **EU West (europe-west4)**.
2. Volume am Service `pretix`, Mount-Pfad `/data`.
3. Variablen am Service `pretix` wie in `.env.example`. Die Geheimnisse
   erzeugt das Skript oder übernimmt sie aus dem Teilnehmer-App-Projekt
   (Mailjet). Ausgegeben werden sie nie.
4. Domain `tickets.skverlag.de` am Service `pretix`, Port 80. Der
   CNAME-Eintrag, den Railway anzeigt, kommt in die DNS-Verwaltung von
   skverlag.de.
5. Backups in Railway für **beide** Volumes (Postgres und pretix), wie bei
   der Teilnehmer-App: täglich, wöchentlich, monatlich.
6. Nach dem ersten erfolgreichen Start:
   - mit `PRETIX_ADMIN_EMAIL` anmelden (Passwort steht in Railway unter
     den Variablen von `pretix`)
   - Zwei-Faktor-Anmeldung einrichten (Pflicht, `PRETIX_PRETIX_OBLIGATORY_2FA`)
   - Variable `PRETIX_ADMIN_PASSWORD` in Railway löschen
   - Testmail aus pretix senden (Veranstalter → E-Mail-Einstellungen). Kommt
     sie nicht an, erlaubt der Railway-Plan kein SMTP.

Eine `railway.json` gibt es bewusst nicht. Railway erkennt das Dockerfile
selbst und startet bei Absturz standardmäßig bis zu 10-mal neu. Die alte
Einstellungsdatei liest Railway nur noch bis 01.12.2026.

**Bewusst ohne Railway-Healthcheck:**
- Railway prüft unter dem Host-Namen `healthcheck.railway.app`. pretix
  beantwortet unbekannte Host-Namen mit 400, also wäre jeder Deploy
  gescheitert.
- Weil der Service ein Volume hat, stoppt Railway den alten Container
  ohnehin vor dem neuen. Die Prüfung brächte also keinen unterbrechungsfreien
  Wechsel.
- Für eine Überwachung eignet sich `https://tickets.skverlag.de/healthcheck/`
  (antwortet 200, solange die Datenbank erreichbar ist).

**Hinweise:**
- Ausgehende Mails per SMTP gehen auf Railway erst ab dem Pro-Plan.
- Jeder Deploy bringt eine kurze Ausfallzeit. Nicht an Verkaufsstarts deployen.

### Wichtige Variablen

| Variable | Zweck |
|---|---|
| `PRETIX_PRETIX_URL` | öffentliche Adresse, `https://tickets.skverlag.de` |
| `PRETIX_DJANGO_SECRET` | geheimer Schlüssel, `openssl rand -hex 50`, nie ändern (sonst sind alle abgemeldet) |
| `PRETIX_DATABASE_*` | Verweise auf den Postgres-Service |
| `PRETIX_REDIS_LOCATION`, `PRETIX_CELERY_*` | Verweise auf den Redis-Service (Datenbanken 0, 1, 2) |
| `PRETIX_MAIL_*` | Mailjet per SMTP (`in-v3.mailjet.com:587`, Benutzer = API-Key, Passwort = Secret) |
| `PRETIX_PRETIX_TRUST_X_FORWARDED_*` | pretix sitzt hinter dem Railway-Proxy |
| `PRETIX_ADMIN_EMAIL`, `PRETIX_ADMIN_PASSWORD` | nur für den ersten Start, siehe oben |
| `NUM_WORKERS`, `CELERY_CONCURRENCY`, `PRETIX_CRON_INTERVAL_SECONDS` | optional, Vorgaben 3 / 2 / 300 |

Jede pretix-Einstellung lässt sich als `PRETIX_<ABSCHNITT>_<NAME>` setzen
([Doku](https://docs.pretix.eu/self-hosting/config/)).

## Shop einrichten

`bin/setup-shop.sh <pretix-adresse>` erledigt die Einrichtung in einem
Durchgang. Christoph führt es aus, weil es per SSH in den Container schreibt.

1. **`bin/bootstrap_organizer.py`** (im Container, per `railway ssh`):
   - legt den Veranstalter `sk` („S+K Verlag“) mit den nötigen Plugins an
   - legt das Team „Administratoren“ mit dem Admin an
   - setzt die **Veranstalter-Einstellungen**, die jede Veranstaltung erbt:
     - Verkäuferangaben auf der Rechnung (aus dem Impressum von skverlag.de)
     - Rechnung mit eingebetteter E-Rechnung (ZUGFeRD, Profil XRechnung)
     - Nummernkreis `SK-`, Testbestellungen bekommen `SK-TEST-`
     - Feld für Leitweg-ID oder Bestellnummer
     - Rechnungsadresse Pflicht, USt-IdNr. abfragbar
     - Überweisung mit 14 Tagen Zahlungsziel, ohne automatischen Verfall, Erinnerung 3 Tage vorher
     - Namen und E-Mail je Ticket, nachträglich änderbar durch Besteller und Teilnehmer
     - Impressum- und Datenschutz-Link
2. **`bin/setup-testshop.py`** (über die API): legt die Testveranstaltung
   `testshop` im Testmodus an. Inhalt:
   - Kongressticket mit Behörde- und Industriepreis
   - Workshops als Zusatz, je Zeitfenster höchstens einer
   - Kombiticket mit Abendessen
   - Streaming-Ticket mit eigener Steuerregel
   - die Fragen `organisation`, `funktion` und `efn`
3. **Noch einmal `bin/bootstrap_organizer.py`:** pretix schreibt beim Anlegen
   einer Veranstaltung eigene Standardwerte an die Veranstaltung, z. B.
   Rechnungsvorlage ohne E-Rechnung und Namensformat ohne Titel. Das Skript
   entfernt diese Kopien, damit die Veranstalter-Einstellungen gelten, und
   schaltet den temporären API-Schlüssel ab.

**Neue Veranstaltungen:** im Backend aus der Testveranstaltung kopieren
oder danach `bin/bootstrap-organizer.sh --no-token` ausführen.

**Offen, bevor echte Tickets verkauft werden:**
- echte Bankverbindung
- Stripe-Schlüssel
- Teilnahmebedingungen / AGB für Veranstaltungen
- Steuerregeln von der Steuerberatung abgenommen (Plan, Abschnitt 12)

**Gefundene pretix-Eigenheiten (2026.9.0):**
- Das E-Rechnungs-Plugin braucht Ghostscript. Ohne Ghostscript entsteht
  stillschweigend keine E-Rechnung. Das Dockerfile installiert es.
- Die API lehnt `name_scheme` nach dem ersten Aufruf je Prozess ab (die
  Auswahl wird aus einem Generator gebaut, `settings.py` Zeile 4061). Das
  Skript versucht es und gibt sonst einen Hinweis aus.
- Rechnungsvorlage, Teilnehmer-Mails und „Rechnung sofort bei Überweisung“
  lassen sich nicht per API setzen, deshalb Schritt 3.

## Updates

pretix erscheint etwa monatlich. Sicherheitskorrekturen gibt es nur für die
letzten drei Versionen, also **spätestens alle drei Monate aktualisieren**.

1. Dependabot öffnet einen PR für das neue Image bzw. Plugin.
2. Der GitHub-Workflow „Build und Starttest“ baut das Image und startet es
   einmal mit Postgres und Redis.
3. Vor dem Merge die Release-Notes lesen
   (https://docs.pretix.eu/self-hosting/updates/), besonders den Abschnitt
   zur Server-Umgebung, und ein manuelles Postgres-Backup in Railway
   anlegen.
4. Merge auf `main` → Railway baut und startet neu. Migrationen laufen beim
   Start automatisch.

## Lizenz

- pretix steht unter der AGPLv3 mit Zusatzbedingungen
  ([LICENSE von pretix](https://github.com/pretix/pretix/blob/v2026.9.0/LICENSE)).
  Der Hinweis **„powered by pretix“** im Footer des Shops darf nicht entfernt
  werden.
- Dieses Repo ist öffentlich und steht ebenfalls unter der AGPLv3
  (`LICENSE`). Damit sind Quellcode und Plugins der laufenden Installation
  offengelegt, wie es die Lizenz in manchen Fällen verlangt (z. B. Verkauf
  für Veranstaltungen Dritter).
- Verwendete Quellen:
  - pretix 2026.9.0: https://github.com/pretix/pretix/tree/v2026.9.0
  - pretix-zugferd (Apache-2.0): https://github.com/pretix/pretix-zugferd
