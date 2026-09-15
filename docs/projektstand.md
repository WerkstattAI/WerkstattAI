# WerkstattAI – Projektstand und nächste Schritte

Stand: 15. September 2026. Grundlage ist eine lokale Codeprüfung mit drei
unabhängigen Teilprüfungen sowie Tests mit synthetischen Daten. Hosting-Konten,
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
| Werkstattverwaltung | Dashboard, Ticketstatus, Notizen, Archiv, Direktannahme und Profile | Kundenberechtigungen und Sitzungswiderruf benötigen weitere Absicherung |
| Werkstattzuordnung | Eigene Kundenlinks, getrennte Demo, Zuordnung von Tickets und Sitzungen | Öffentliche Kundenlinks ersetzen keinen Identitätsnachweis |
| WhatsApp | Signaturprüfung, Posteingang, manuelle Antworten, Vorlagen, Zustellstatus und Übernahme durch Mitarbeiter | Zeitfenster, Fehlerwiederholung und konkurrierende Übernahme sind noch nicht durchgehend robust |
| Konten und Abo | Benutzerverwaltung, Rollen und Trial-/Abo-Status | Statusverwaltung ist kein Nachweis eines vollständigen Zahlungs- und Abrechnungsprozesses |
| Datenschutz | Rechtstextentwürfe, Export, Löschvorschau, Passwortbestätigung, Vorgangsvermerke und AVV-Grundlage | Anbieterangaben, Verträge, verbindliche Fristen und externe Bestände offen |
| HTTP-Schutz | Sicherheitsheader, Eingabegrenzen, Signaturkontrolle und gemeinsame Rate-Limits | Ersetzt keine vollständige Objektberechtigung und keine Paketaktualisierungen |

## Priorisierte Arbeitspakete

### 1. Kundenberechtigungen und Sitzungen – vor echten Kundendaten

- Bestehende Vorgänge erst nach Prüfung der Berechtigung des jeweiligen Kunden
  anzeigen oder ändern; dies für Webchat und WhatsApp durchsetzen.
- Web- und WhatsApp-Sitzungen serverseitig voneinander trennen und öffentliche
  Sitzungen wirksam an ihren Benutzer beziehungsweise Browser binden.
- Benutzerlöschung, Rollenwechsel und Passwortreset müssen bestehende Zugriffe
  widerrufen. Alle Dashboard- und API-Wege müssen denselben aktuellen
  Berechtigungsstand prüfen.
- Die in der isolierten Prüfung bestätigten Fehlverhalten als Sicherheitstests
  festhalten; ein Fix gilt erst mit bestandenen Regressionstests als abgeschlossen.

Diese Punkte wurden mit synthetischen Daten reproduziert. Technische
Reproduktionsdetails gehören in die betreute Behebung und sind hier nicht als
öffentliche Schrittfolge dokumentiert. Betroffene Bereiche sind
`app/conversation/existing_ticket.py`, `app/conversation_sessions.py`,
`app/auth.py`, `app/main.py` und `app/web.py`.

### 2. WhatsApp zuverlässig abschließen

- Das 24-Stunden-Fenster anhand des tatsächlichen Zeitpunkts der letzten
  Kundennachricht berechnen, einschließlich verspäteter Webhooks.
- Fensterprüfung an einer gemeinsamen Stelle für jeden Freitext-Versand
  durchsetzen; automatische Antworten einschließen.
- Nach Verarbeitungs- oder Versandfehlern Wiederaufnahme ermöglichen. Eine
  bereits gespeicherte Eingangsnachricht darf nicht automatisch als vollständig
  verarbeitet gelten.
- Eine zwischenzeitliche Mitarbeiterübernahme darf nicht durch eine laufende
  automatische Antwort zurückgesetzt werden.
- Bilder und Sprachnachrichten benötigen einen verständlichen Bearbeitungsweg.

Die ersten vier Punkte wurden mit simuliertem Versand reproduziert. Die
[WhatsApp Business Messaging Policy](https://business.whatsapp.com/policy)
erlaubt Freitextantworten innerhalb von 24 Stunden nach der letzten
Kundennachricht; außerhalb dieses Fensters sind genehmigte Vorlagen erforderlich.

### 3. Abhängigkeiten und Produktionsprüfung

- FastAPI, Starlette und python-multipart als kompatiblen Satz aktualisieren
  und testen. Die gepinnten Versionen enthalten bekannte Parser-Schwachstellen.
  Eigene Body- und Rate-Limits mindern die Exposition, ersetzen die Updates aber
  nicht. Ein Live-Angriff wurde nicht durchgeführt.
- Reproduzierbare Testabhängigkeiten und CI einrichten. `httpx` wird für die
  Anwendungstests benötigt und ist bisher nicht separat deklariert.
- Python 3.12 mit den tatsächlichen Docker-Abhängigkeiten sowie PostgreSQL
  testen. Der lokale Testlauf verwendet Python 3.14.3, Pydantic 2.12.5 und SQLite;
  der PostgreSQL-Treiber ist in dieser Testumgebung nicht installiert.
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

- Nach den Korrekturen: **163 Python-Tests und 3 Worker-Tests bestanden**.
  Die bestehenden Tests decken die zusätzlich reproduzierten Sicherheits- und
  WhatsApp-Fehler noch nicht als Schutzanforderungen ab.
- Sicherheitsreproduktionen verwenden ausschließlich temporäre SQLite-Daten
  und gemockten Nachrichtenversand. Keine produktiven Kundendaten abgerufen.
- Kein Browser für visuelle Kontrolle verbunden; Oberfläche über TestClient
  geprüft. Kein produktiver PostgreSQL-, Backup- oder Lasttest durchgeführt.
- Ein Scan der zu versionierenden Textdateien auf ausgewählte Secret-Muster
  ergab keine Treffer. `.env`, `data/` und `.venv/` bleiben Git-ignoriert. Dies
  ist keine vollständige forensische Prüfung der Git-Historie.
- Der Upload auf einen Prüfbranch ist keine Produktionsfreigabe. Die offenen
  Arbeitspakete bleiben bis zu ihrer Umsetzung und Überprüfung offen.
