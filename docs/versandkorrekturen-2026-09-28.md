# Gezielte Versandkorrekturen vom 28. September 2026

Branch: `codex/kundenkommunikation-2026-09-26`. Kein Merge, kein Deployment und
keine produktiven Daten oder Nachrichten. Die bestehende Kommunikationsarchitektur
mit Ticketnotizen, Kontrollrevisionen und kurzen Transaktionen bleibt maßgeblich.

## Bestätigte Ursachen

1. `send_workshop_message()` behandelt jede bereits gespeicherte Nachrichten-ID
   als denselben Versuch. Der Browser behielt diese ID auch nach einer eindeutigen
   Ablehnung. Unveränderter Text führte damit immer wieder zum alten Fehler.
2. Die Reservierung `dispatch_state=sending` wird vor dem externen HTTP-Aufruf
   gespeichert. Nach Prozessabbruch fehlten sowohl ein verlässlicher Startzeitpunkt
   als auch ein kontrollierter Weg zur Klärung. Ein späterer normaler Abschluss
   schrieb außerdem ohne Prüfung des noch gültigen Versandanspruchs.

## Bewusster Neuversuch nach einem Fehler

- Die Oberfläche zeigt „Nachricht nicht gesendet“ und bietet „Erneut senden“.
  Text, Zweck und konkretes Antwortziel bleiben im Browserentwurf erhalten.
- Erst das bewusste Absenden erneuert die ID. Ein Seitenaufruf sendet nichts.
  Ticket, Posteingang, Dashboarddialog sowie Diagnose-/Startvorlagenformulare
  verwenden denselben Schutzgedanken.
- Der Server erhält den alten `failed`-Versuch unverändert. Dieselbe ID bleibt
  idempotent; ein neuer Versuch besitzt eine neue Transportzeile und Ticketnotiz.
- Eine fehlgeschlagene Antwort schließt keine Frage. Erst der erfolgreiche neue
  Versuch löst genau das gespeicherte Antwortziel auf. Das 24-Stunden-Fenster
  wird auch beim Neuversuch erneut serverseitig geprüft.

## Manuelle Klärung eines unklaren Versands

`dispatch_started_at` speichert den Reservierungsbeginn ausdrücklich mit UTC-Offset.
Manuelle und automatische Sendungen verwenden dieses Feld. Die additive Migration
ergänzt es wiederholbar auf SQLite/PostgreSQL. Alte `sending`-Zeilen ohne Zeitpunkt
erhalten einmalig eine neue fünfminütige Schutzfrist; ein wiederholter Start setzt
diese Frist nicht zurück. Ungültige oder mehrdeutige Zeitwerte erlauben keine Klärung.

Eine ungeklärte Reservierung blockiert den weiteren Versand und die Rückgabe an
den Assistenten. Nach mindestens fünf Minuten erscheint:

> Der Versandstatus ist unklar. Prüfen Sie den tatsächlichen Status bei Meta, bevor Sie fortfahren.

Die zwei Aktionen verlangen eine ausdrückliche Bestätigung und einen Dialog:

- **Als gesendet bestätigen:** Transport `complete`, Nachricht `sent`. Eine
  Werkstattantwort schließt nur ihr konkretes Frageziel; Informationen schließen
  keine Fragen. Neuere Bearbeitung und Kundenantworten bleiben maßgeblich.
- **Als nicht gesendet bestätigen und entsperren:** Transport `complete`, Nachricht
  `failed`. Keine Frage wird geschlossen. Anschließend ist ein bewusster Neuversuch
  mit neuer ID möglich. Ein vorheriger Gesprächszustand wird nur zurückgesetzt,
  wenn Kontrollrevision, Ticketzuordnung und gespeicherter Stand der Ticketnotizen
  sowie Kundeneingänge weiterhin übereinstimmen. Fehlt der Nachweis, bleibt der
  aktuelle Gesprächszustand erhalten.

`manual_resolution` protokolliert Entscheidung, authentifizierte Benutzeradresse,
UTC-Zeitpunkt und Bestätigung im vorhandenen `payload_json`. `status_source` benennt
die manuelle Bestätigung. Gleiche wiederholte Klärungen erzeugen keinen neuen Audit-
oder Fachabschluss; widersprüchliche Entscheidungen werden abgelehnt.

## Schutz vor Doppelversand und konkurrierenden Änderungen

- Der Dashboard-Endpunkt prüft die aktuelle signierte Sitzung mit dem aktuellen
  Datenbanknutzer und dessen Rolle. Wie im übrigen Dashboard darf nur `admin` eine
  andere Werkstatt wählen; andere Werkstattrollen bleiben an den eigenen Mandanten
  gebunden. Eine fremde Nachrichten-ID gewährt keinen Zugriff. Bestehender Origin-
  und Cookie-Schutz gilt auch für die neue POST-Aktion.
- Zeitgrenze und Zustand werden beim Update unter `atomic_database()` und der
  vorhandenen Kommunikationssperre erneut geprüft. HTTP-Abschluss, Meta-Rückmeldung
  und Klärung benutzen eine gemeinsame bedingte Abschlussfunktion. Nur ein noch
  passender `sending`-Anspruch kann abgeschlossen werden.
- HTTP-Aufrufe bleiben außerhalb der Datenbanktransaktion. Auch ein verspätetes
  HTTP-Ergebnis überschreibt eine bereits gespeicherte manuelle Entscheidung nicht.
- Neue unklare HTTP-Ergebnisse bleiben `unknown/sending` und werden nicht automatisch
  wiederholt. Eine zuordenbare Meta-Bestätigung oder die manuelle Klärung kann sie
  abschließen. Frühere `complete/unknown`-Altdaten werden nicht rückwirkend umgedeutet.
- Verspätete Meta-Ereignisse werden nachvollziehbar gespeichert. Sie können
  fehlgeschlagene oder manuell geklärte Versuche nicht wiederbeleben. Bei gewöhnlich
  gesendeten Nachrichten bleiben fortschreitende Zustellbestätigungen und die
  bestehende Anzeige belegter Meta-Zustellfehler erhalten, ohne erneut Fragen oder
  Gesprächszustände zu bearbeiten. `delivered/read` werden nicht zurückgestuft.
- Auftragsstatus wie `offen`, `in_bearbeitung` und `erledigt` bleiben unverändert.

## Geänderte Dateien

| Dateien | Zweck |
| --- | --- |
| `app/db.py` | Additiver UTC-Zeitpunkt und Schutzfrist für Altbestand |
| `app/manual_dispatch.py`, `app/whatsapp.py`, `app/tickets.py` | Reservierung, gemeinsamer bedingter Abschluss, unveränderliche Fehlversuche und Schutz neuerer Zustände |
| `app/dispatch_recovery.py` | Lesekontext, Zeitprüfung und auditierte Klärung |
| `app/web.py` | Geschützter Endpunkt, Formularkennungen und Anzeige-Kontexte |
| `templates/_communication.html`, `_communication_script.html`, `ticket.html`, `whatsapp.html`, `dashboard.html` | Bewusster Neuversuch, Warnungen, Bestätigungen und Formularsperren |
| `tests/test_dispatch_recovery.py`, `test_communication_composer.mjs`, `test_communication_ui.py` | Gezielte Regressionen für Datenbank, HTTP-Zugriff und Oberfläche |
| `docs/kundenkommunikation.md`, dieses Dokument | Aktualisierte Betriebs- und Verifikationsbeschreibung |

## Verifikation

Abschließende lokale Verifikation am 1. Oktober 2026 auf
`codex/kundenkommunikation-2026-09-26`, ausgehend von Commit `cdd76c0`:

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -q`
  (Projektinterpreter für `python -m unittest discover -s tests -q`): 347 Tests in
  149,725 Sekunden, 346 bestanden, 1 übersprungen, keine Fehler;
  `OK (skipped=1)`, Exitcode 0.
- `node --test tests/test_communication_composer.mjs tests/test_privacy_worker.mjs`:
  18 Tests bestanden, keine Fehler oder übersprungenen Tests, Exitcode 0.
- `git diff --check`: keine Whitespace-Fehler, Exitcode 0.

Übersprungen blieb
`test_communication_postgres.PostgreSQLCommunicationTests.test_fresh_schema_legacy_migration_and_targeted_delivery`,
weil `WERKSTATTAI_TEST_POSTGRES_URL` nicht gesetzt ist. Eine ausdrücklich konfigurierte,
entbehrliche PostgreSQL-Testdatenbank liegt nicht vor; der reale PostgreSQL-Pfad
ist deshalb in diesem Lauf nicht verifiziert.

Der bisher kombinierte Timeout-/Abbruchtest wurde in zwei unabhängige Tests mit
jeweils frischer temporärer SQLite-Datenbank aufgeteilt. Nach dem Timeout bleibt
die erste Reservierung korrekt `unknown/sending`; eine weitere Nachricht derselben
Unterhaltung erhält daher HTTP 503, bevor ein simulierter `KeyboardInterrupt`
erreicht werden könnte. Dies war die Ursache des bisherigen Testfehlers.

- Der Timeout-Test prüft genau einen Transportaufruf, das Ignorieren desselben
  Webhook-Ereignisses und die unveränderte Reservierung. Eine weitere Nachricht
  und deren Wiederholung erhalten jeweils HTTP 503, behalten ihre Antwort als
  `pending/pending` ohne Versandbeginn und lösen keinen zusätzlichen Transport
  oder wiederholte fachliche Verarbeitung aus.
- Der Abbruchtest beginnt ohne bestehende Nachrichten, prüft die bereits gespeicherte
  Reservierung beim Transportaufruf und simuliert dann `KeyboardInterrupt`.
  Die Reservierung bleibt nach Abbruch und Webhook-Wiederholung unverändert;
  insgesamt erfolgt ein Transportaufruf, bei der Wiederholung keiner.

Produktionscode und Produktionssperre blieben unverändert. Sämtliche Versandaufrufe
in den Regressionen sind simuliert; die Daten stammen ausschließlich aus temporären
synthetischen Testbeständen. Es gab keinen Merge, kein Deployment und keinen Zugriff
auf produktive Nachrichten oder Datenbanken. Der Python-Lauf meldete weiterhin
`ResourceWarning`- und `DeprecationWarning`-Hinweise; der protokollierte simulierte
`RuntimeError` des Rollback-Tests ist erwartet und kein Testfehler.

## Bewusste Grenzen

Fünf Minuten sind eine Schutzfrist, kein Nachweis für einen fehlgeschlagenen Versand.
Eine falsche manuelle Bestätigung „nicht gesendet“ kann bei einem späteren Neuversuch
zu Doppelzustellung führen. Die tatsächliche Prüfung bei Meta bleibt deshalb
erforderlich. Bei einem außergewöhnlich lange blockierten Prozess kann trotz
abgelaufener Frist noch ein HTTP-Ergebnis eintreffen; die Datenbank schützt die
gewählte Entscheidung, kann aber eine bereits erfolgte externe Zustellung nicht
rückgängig machen. Ohne Meta-ID ist eine automatische Zuordnung späterer
Zustellereignisse nicht möglich.

Es gibt keine automatische Auflösung alter Reservierungen, keinen Hintergrund-
Retry unklarer Ergebnisse und keine echte Meta-Sendung in dieser Verifikation.
Die bestehende automatische Wiederaufnahme eindeutig abgelehnter vorläufiger
Assistentenversuche bleibt erhalten; sie betrifft keine unklaren Ergebnisse.
