# WerkstattAI – Projektstand und nächste Schritte

## Aktueller Stand vom 19. Oktober 2026

Die Dashboard-Überarbeitung und die geschützte WhatsApp-Bildvorschau sind im
Projekt gespeichert und veröffentlicht. Anwendungsstand:
`aa965e481f62ad34ee752d5b3cd89f365c4d30fb`, Branch
`codex/kundenkommunikation-2026-09-26`. Das Railway-Deployment
`e81fee99-9838-4ee3-9639-ba2674b3537b` wurde am 19. Oktober mit Status
`SUCCESS`, laufender Instanz und acht erfolgreichen Onlinekontrollen bestätigt.
Anwendung: https://werkstattai-whatsapp.up.railway.app

- **Dashboard:** kompaktere Tagesübersicht, offene Aufgaben vor der Suche,
  zusätzliche Filter aufklappbar, verbesserte Mobilansicht, neue Hinweise sowie
  Statusaktionen ohne Seitenwechsel. Die vorbereiteten Korrekturen vom
  11. Oktober sind enthalten; Entwürfe, Filter und Listenposition bleiben erhalten.
- **WhatsApp-Fotos:** JPEG/PNG sind im Posteingang und bei vorhandener
  Ticketzuordnung im Gesprächsverlauf sichtbar. Abruf nur nach Anmeldung und
  innerhalb der berechtigten Werkstatt. Fotos werden als Kundeninformation zur
  Prüfung markiert; keine OCR oder automatische Reparaturfreigabe. Es gibt noch
  keine dauerhafte Dokumentenablage. Einzelheiten: [WhatsApp-Bilder](whatsapp-bilder.txt).
- **Verifikation:** 526 von 526 Python-Tests unter Python 3.12 mit gepinnten
  Abhängigkeiten und isoliertem PostgreSQL 18 bestanden; zusätzlich 35 von 35
  JavaScript-Tests und acht Onlinekontrollen nach Veröffentlichung.
  Ein tatsächlicher Meta-Bilddownload und eine reale WhatsApp-Unterhaltung mit
  bestätigtem eigenen Testempfänger bleiben gesondert zu prüfen.
- **Meta-Konto:** Cloud API technisch verbunden und App im Modus Live.
  Direkt im angemeldeten Business-Portfolio wurde jedoch „Nicht verifiziert“
  bestätigt; eingetragener Unternehmensname, Adresse, Telefonnummer und Website
  fehlen. Der Tech-Provider-Prozess ist noch nicht abgeschlossen. Der
  Informationsdialog verlangt Unternehmensverifizierung, Zugriffsverifizierung
  und App-Review. Es wurden keine Meta-Einstellungen oder Firmenangaben geändert.
- **Fremde Werkstattnummern:** ein vollständiger Embedded-Signup-Prozess mit
  erforderlichem Berechtigungs-/Tokenaustausch und werkstattspezifischer
  Kontoverwaltung ist noch zu implementieren. Eine veröffentlichte App und ein
  gültiger Testzugang allein bestätigen diese Möglichkeit nicht.
- **Projektsprache:** neue Oberflächentexte, Kommentare, Docstrings,
  Fehlermeldungen und Dokumentation auf Deutsch; in [AGENTS.md](../AGENTS.md)
  dauerhaft festgehalten. Bestehende Schnittstellenbezeichner bleiben kompatibel.

### Nächste Schritte

1. Das bestehende Administratorpasswort ändern; die Anmeldung mit dem bekannten
   Standardpasswort wurde bestätigt. Eine Änderung allein der Railway-Startvariable
   setzt das Passwort eines bestehenden Benutzers nicht zurück.
2. Tatsächliche Unternehmensdaten und erforderliche Gewerbe-/Steuerfragen klären,
   anschließend Meta-Unternehmensverifizierung und Tech-Provider-Freigaben bearbeiten.
   Eine Gewerbeanmeldung allein schaltet die Meta-Freigaben nicht automatisch frei.
3. Onboarding fremder Werkstätten und ihrer WhatsApp-Konten umsetzen und mit
   autorisierten Konten sowie echten Testnachrichten prüfen.
4. Bekannte Sicherheitsupdates der Pakete, Anbieterangaben, Backup-/Restore-
   Nachweise und Betriebsüberwachung abschließen. Der folgende historische
   Prüfumfang ist keine aktuelle Freigabe dieser offenen Punkte.

Die ausführlichen lokalen Nachweise und Screenshots liegen unter
`artifacts/readiness-2026-10-19/`, insbesondere `ABSCHLUSSBERICHT.txt`,
`railway_aktuell.json` und `meta_konto_ui.json`. Diese lokalen Prüfartefakte,
Datenbanken und Zugangsdaten werden weder in Git noch in Docker aufgenommen.

## Historischer Prüfstand vom 26. September 2026

Die folgenden Abschnitte dokumentieren den damaligen Ausgangsstand. Für bereits
umgesetzte Arbeiten und heutige Testergebnisse gilt die Aktualisierung oben.

Stand: 26. September 2026. Grundlage sind lokale Codeprüfungen, die anschließenden
Sicherheitskorrekturen und Tests mit synthetischen Daten. Hosting-Konten,
produktive Datenbanken und reale WhatsApp-Nachrichten wurden nicht geprüft.

## Einschätzung

**Funktionaler Prototyp mit wesentlichen MVP-Funktionen. Vor einem Pilotbetrieb
mit echten Kundendaten sind noch Sicherheits- und Betriebsprobleme zu beheben.**

Eine Prozentzahl würde die offenen Sicherheitsfragen verdecken. Der nächste
Meilenstein ist ein nachweislich abgesicherter Pilot, anschließend regulärer
Betrieb. Erfolgreiche Funktionstests sind keine Sicherheits- oder Rechtsfreigabe.

## Vorhandene Funktionen

| Bereich | Stand | Wesentliche Grenze |
| --- | --- | --- |
| Kundenannahme | Webchat, strukturierte Aufnahme, Rückfragen, Priorität und Tickets | Regelbasierter Assistent; keine aktive externe KI-Anbindung im geprüften Code |
| Werkstattverwaltung | Dashboard, Ticketstatus, Notizen, Archiv, Direktannahme und Profile | Kundenberechtigungen und Sitzungswiderruf lokal korrigiert; Einspielen und Produktionsprüfung offen |
| Werkstattzuordnung | Eigene Kundenlinks, getrennte Demo, Zuordnung von Tickets und Sitzungen | Öffentliche Kundenlinks ersetzen keinen Identitätsnachweis |
| WhatsApp | Signaturprüfung, Posteingang, manuelle Antworten, Vorlagen, Zustellstatus und Übernahme durch Mitarbeiter | Zeitfenster, Fehlerwiederholung und Übernahme lokal abgesichert; Meta-Testkonto und PostgreSQL noch zu prüfen |
| Konten und Abo | Benutzerverwaltung, Rollen und Trial-/Abo-Status | Statusverwaltung ist kein Nachweis eines vollständigen Zahlungs- und Abrechnungsprozesses |
| Datenschutz | Rechtstextentwürfe, Export, Löschvorschau, Passwortbestätigung, Vorgangsvermerke und AVV-Grundlage | Anbieterangaben, Verträge, verbindliche Fristen und externe Bestände offen |
| HTTP-Schutz | Sicherheitsheader, Eingabegrenzen, Signaturkontrolle und gemeinsame Rate-Limits | Ersetzt keine vollständige Objektberechtigung und keine Paketaktualisierungen |

## Kundenkommunikation erweitert

Die nachfolgende Überarbeitung trennt Absender, Nachrichtenzweck und
Gesprächszustand. Gezielte Antworten lösen einzelne Kundenfragen; Rückfragen und
Informationen ändern den Ticketstatus nicht. Die additive Migration wurde mit
SQLite und einer isolierten PostgreSQL-18-Datenbank geprüft. Details, geänderte
Dateien, Legacy-Behandlung und Grenzen stehen unter
[Kundenkommunikation](kundenkommunikation.md). Das ist weiterhin eine lokale
Implementierung, keine Bestätigung des produktiven Betriebs.

## Priorisierte Arbeitspakete

### 1. Kundenberechtigungen und Sitzungen – lokal korrigiert

- Eigene Tickets werden anhand der gebundenen Browsersitzung beziehungsweise
  des bestätigten WhatsApp-Absenders freigegeben. Eingegebene Kontakttelefonnummern
  und Ticketnummern allein erteilen keinen Zugriff.
- Web- und WhatsApp-Sitzungen sind serverseitig getrennt. Ein signiertes
  HttpOnly-Cookie bindet Webgespräche an ihren Browser und ihre Werkstatt.
- Dashboard und API prüfen die aktuelle Benutzerzuordnung bei jedem Zugriff.
  Passwortreset, Benutzerlöschung sowie Rollen-/Werkstattwechsel entziehen
  bisherigen Anmeldungen den Zugriff.
- Regressionstests prüfen fremde Zugriffe, Mandantentrennung, manipulierte Cookies,
  Sitzungsübernahme sowie die eigenen berechtigten Abläufe.

Beim Einspielen müssen Nutzer sich neu anmelden; alte öffentliche Webgespräche
werden nicht automatisch übernommen. Historische Tickets bleiben für die Werkstatt
zugänglich. Einzelheiten stehen in den [Einspielhinweisen](sicherheitskorrekturen-2026-09-26.md).

### 2. WhatsApp – wesentliche Logikfehler lokal korrigiert

- Das 24-Stunden-Fenster nutzt den Meta-Zeitpunkt der letzten Kundennachricht.
  Verspätete, fehlende oder ungültige Zeitpunkte eröffnen kein neues Fenster.
- Automatische Antworten und der gemeinsame Freitextsender prüfen das Fenster.
- Eingang, Ticketänderungen, Notizen, Sitzung und vorbereitete Antwort werden
  atomar gespeichert. Verarbeitungsausfälle können erneut versucht werden;
  bereits vorbereitete Antworten wiederholen die Kundenannahme nicht.
- Unklarer Versand nach Timeout/Abbruch wird nicht blind wiederholt. Eine
  zwischenzeitliche Mitarbeiterübernahme wird nicht zurückgesetzt.
- Gleichzeitige Ticketnotizen werden durch Datenbanktransaktionen geschützt.

Noch offen: Erprobung mit Meta-Testkonto und Produktionsdatenbank, ein betrieblicher
Ablauf für unklare Sendungen, eine Hintergrundwarteschlange für ausstehende Antworten
sowie ein verständlicher Bearbeitungsweg für Bilder und Sprachnachrichten.

### 3. Abhängigkeiten und Produktionsprüfung

- FastAPI, Starlette und python-multipart als kompatiblen Satz aktualisieren
  und testen. Die gepinnten Versionen enthalten bekannte Parser-Schwachstellen.
  Eigene Body- und Rate-Limits mindern die Exposition, ersetzen die Updates aber
  nicht. Ein Live-Angriff wurde nicht durchgeführt.
- Reproduzierbare Testabhängigkeiten und CI einrichten. `httpx` wird für die
  Anwendungstests benötigt und ist bisher nicht separat deklariert.
- Python 3.12 mit den tatsächlichen Docker-Abhängigkeiten sowie PostgreSQL
  testen. Der lokale Testlauf verwendet Python 3.14.3, Pydantic 2.12.5 und SQLite;
  der PostgreSQL-Treiber ist in der lokalen virtuellen Umgebung nicht installiert.
  Die neue Kommunikationsmigration wurde zusätzlich isoliert mit PostgreSQL 18,
  Python 3.12 und psycopg 3.2.3 getestet; ein vollständiger Produktionstest bleibt offen.
- Schemaänderungen an einer bestehenden Testdatenbank prüfen und einen
  nachvollziehbaren Migrations-/Wiederherstellungsablauf festlegen.
- Einen separaten Bereitschaftscheck ergänzen, der einen Datenbankausfall
  erkennt; `/health` ist bisher nur ein Lebenszeichen der Anwendung.

Primärquellen für Paketprobleme:
[python-multipart CPU-/Logging-DoS](https://github.com/Kludex/python-multipart/security/advisories/GHSA-59g5-xgcq-4qw3),
[Multipart-Header-Grenzen](https://github.com/Kludex/python-multipart/security/advisories/GHSA-pp6c-gr5w-3c5g),
[Starlette-Formularlimits](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq).

### 4. Rechtliche und betriebliche Vorbereitung abschließen

- Geschäftsanschrift, rechtlichen Anbieter, Rechtsform und erforderliche weitere
  Angaben vervollständigen und fachkundig prüfen lassen.
- Hosting-Region, Unterauftragsverarbeiter, Vertragsbezug und Drittlandtransfers
  für die tatsächlich eingesetzten Konten bestätigen.
- Vereinbarungen mit Werkstätten und erforderlichen Dienstleistern abschließen.
- Speicherfristen, Löschabläufe, Backups, Wiederherstellung nach Löschanfragen
  und Vorfallzuständigkeiten verbindlich festlegen und praktisch prüfen.

Details stehen unter [Datenschutz: Betrieb und offene Angaben](recht/betrieb-und-freigabe.md)
und in der [AVV-Grundlage](recht/avv-grundlage.md).

### 5. Bedienung für den Pilotbetrieb verbessern

- Vollständige werkstattspezifische Kundenlinks mit Kopierfunktion bereitstellen.
- Mit zwei getrennten Testwerkstätten den gesamten Weg von Anfrage über
  Bearbeitung bis Export und Löschung durchspielen.
- Einen betreuten Pilot mit klaren Ansprechpartnern und überprüfbaren
  Erfolgskriterien vorbereiten, sobald die vorstehenden Sperrpunkte erledigt sind.

## In dieser Prüfung direkt korrigiert

- `.dockerignore` ergänzt: lokale Umgebungsdateien, Datenbanken, Git-Metadaten
  und virtuelle Umgebungen werden vom Docker-Build-Kontext ausgeschlossen.
  Das verhindert deren versehentliche Übernahme durch `COPY . .`; bereits
  existierende Images sind dadurch nicht rückwirkend geprüft oder bereinigt.
- Datenschutzlink im Kundenchat verwendet jetzt die tatsächlich übergebene
  Werkstattkennung. Bestehende Tests prüfen diese Zuordnung für zwei Werkstätten.
- Vorbereitete Rechtstexte, Datenverwaltung, AVV und dazugehörige Tests sind
  Bestandteil des gesicherten Projektstands.

## Grenzen der Aussage

- Nach den Korrekturen: **216 Python-Tests im Gesamtlauf und 3 Worker-Tests bestanden**.
  Nach der letzten Änderung an der Tickettransaktion wurden zusätzlich die
  betroffenen Ticket-/Datenschutztests und 13 WhatsApp-Tests einschließlich
  paralleler Notizspeicherung geprüft.
  Die ergänzten Tests decken auch die bestätigten Zugriffs- und WhatsApp-Fehler ab.
- Sicherheitsreproduktionen verwenden ausschließlich temporäre SQLite-Daten
  und gemockten Nachrichtenversand. Keine produktiven Kundendaten abgerufen.
- Kein Browser für visuelle Kontrolle verbunden; Oberfläche über TestClient
  geprüft. Kein produktiver PostgreSQL-, Backup- oder Lasttest durchgeführt.
- Ein Scan der zu versionierenden Textdateien auf ausgewählte Secret-Muster
  ergab keine Treffer. `.env`, `data/` und `.venv/` bleiben Git-ignoriert. Dies
  ist keine vollständige forensische Prüfung der Git-Historie.
- Der Upload auf einen Prüfbranch ist keine Produktionsfreigabe. Die offenen
  Arbeitspakete bleiben bis zu ihrer Umsetzung und Überprüfung offen.
