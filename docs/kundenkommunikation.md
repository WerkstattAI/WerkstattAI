# Kundenkommunikation: Zustände, Nachrichten und Migration

## Ursache und neues Modell

Früher bedeutete `customer_message` zugleich „Kundennachricht“ und „offene Frage“.
Jede `customer_reply` schloss diese Markierung und konnte den Reparaturstatus
ändern. Das vermischte Gesprächsführung, Nachrichteninhalt und Auftragsbearbeitung.

Die Nachrichten bleiben im vorhandenen Ticketverlauf `notes_json`. Sie tragen
zusätzlich stabile `message_id`, `sender_role`, `purpose`,
`requires_human_action`, `reply_to_message_id` und `resolved_at`.
Die Rollen sind `customer`, `assistant` und `workshop`. Die Zwecke sind
`intake_question`, `automatic_answer`, `customer_question`,
`customer_information`, `workshop_answer`, `workshop_question`,
`workshop_notification` und `internal_note`.

`customer_question_open` ist ein abgeleiteter Kompatibilitätswert aus den
unbeantworteten Kundenfragen. Der Reparaturstatus ändert sich ausschließlich
über die vorhandenen Statusaktionen.

| Gesprächszustand | Bedeutung |
| --- | --- |
| `assistant_active` | Automatik darf den Auftrag aufnehmen und gespeicherte Fakten beantworten. |
| `waiting_for_workshop` | Die Werkstatt muss die Frage oder Information bearbeiten; Automatik pausiert. |
| `workshop_active` | Das Team hat übernommen; Automatik pausiert. |
| `waiting_for_customer` | Eine konkrete Werkstattfrage wartet auf die nächste Kundenantwort. |

Sobald ein Ticket zugeordnet ist, ist `tickets.conversation_state` maßgeblich.
WhatsApp-Kontrollen projizieren diesen Zustand; `mode` bleibt als abgeleitete
Kompatibilitätsschnittstelle erhalten. Bei Gesprächen ohne Ticket liegt der
Zustand in der vorhandenen WhatsApp-Kontrolle. Im Intake-State wird kein zweiter
Gesprächszustand gespeichert.

## Fachliches Verhalten

- Nach der Aufnahme beantwortet der Assistent nur eindeutig gespeicherte Fakten.
  Diese Eingänge und automatischen Antworten erzeugen keine offene Kundenfrage.
- Preis, Diagnose, Fertigstellung, Dauer, Termine, Teile und unklare Entscheidungen
  werden der Werkstatt übergeben. Eine einmalige Bestätigung wird protokolliert.
- Frische manuelle Nachrichten beginnen mit „Zweck auswählen …“. Eine
  Werkstattantwort benötigt eine bewusst gewählte offene Kundenfrage, auch wenn
  nur eine offen ist. Die Formularpfade weisen fehlende oder ungültige Auswahlen
  vor Speicherung beziehungsweise Versand ab; nur das gewählte Ziel erhält
  `resolved_at`. Bei WhatsApp geschieht dies nach erfolgreichem Versand, beim
  Web-Chat bereits beim Speichern der Antwort, ohne einen Lesenachweis.
- Neue Browserentwürfe speichern, ob Zweck und Ziel bewusst gewählt wurden.
  Gültige Auswahlen und fehlgeschlagene Versuche bleiben erhalten. Alte Entwürfe
  ohne diesen Nachweis behalten ihren Text, benötigen aber eine erneute Auswahl.
  Ein inzwischen geschlossenes Antwortziel wird nicht automatisch ersetzt.
- Werkstattinformationen schließen keine Fragen und verändern keinen Ticketstatus.
- Werkstattfragen pausieren die Automatik. Eine inhaltliche Kundenantwort erhält
  deren Nachrichten-ID als Antwortbezug und wird nicht als Intake-Antwort behandelt.
  Ein reines Empfangszeichen wie „Danke“ beantwortet die Frage nicht: sie bleibt
  offen, der Zustand bleibt `waiting_for_customer`, und es entsteht keine neue
  Bearbeitungsaufgabe. Daraus wird keine Reparaturfreigabe abgeleitet.
- Im Ticket kann die Werkstatt eine prüfbedürftige Kundeninformation ausdrücklich
  „Als bearbeitet markieren“. Nur diese Information erhält `resolved_at`; offene
  Fragen, Gesprächsübernahme und Reparaturstatus bleiben unverändert.
- Die bewusste Rückgabe „Assistent übernimmt“ beendet noch ausstehende
  Werkstatt-Rückfragen mit `response_cancelled_at`. Offene Kundenfragen bleiben
  erhalten. Textklassifikation kann die manuelle Übernahme nicht aufheben.

## Aufnahme in Webchat und WhatsApp

Die Aufnahme nutzt in beiden Kanälen dieselbe Feldextraktion und Validierung.
Meldungseinleitungen, auch mit kleinen Tippfehlern, starten die Aufnahme, ohne
selbst als Defekt gespeichert zu werden. Enthaltene konkrete Anliegen bleiben
erhalten. Eindeutige Fahrzeug-, Jahres-, Kilometer- und Kontaktangaben werden
gemeinsam verarbeitet; ausdrückliche Korrekturen ersetzen die betreffenden
Felder auch außerhalb des gerade abgefragten Schritts.

Ein ausdrücklich neues Anliegen nach einer abgeschlossenen Aufnahme erhält
einen frischen Intake-State ohne alte Ticket-ID oder Problemdaten. WhatsApp
übernimmt eine ausdrücklich geleerte Ticket-ID auch in die Transportkontrolle,
statt erneut die vorherige ID einzusetzen. Bei unklarer Absicht fragt der
Assistent nach neuem Anliegen oder Ergänzung. Ergänzungen und Statusabfragen
bleiben beim bestehenden Zugriffsschutz. Manuelle Übernahmen und ausstehende
Werkstattfragen behalten die oben beschriebenen Regeln.

Abbruchbefehle werden vor der Feldverarbeitung behandelt. Symptome, Nichtwissen
und Befehle werden nicht als Fahrzeug oder Name gespeichert. Die
Symptomerkennung verwendet Wortgrenzen und berücksichtigt einfache
Verneinungen. Niedrige Kilometerstände werden im Kilometerstand-Schritt auch
ohne Einheit akzeptiert; Jahreszahlen im Freitext werden dadurch nicht pauschal
zu Kilometerständen. Nebenfragen zu hinterlegten Werkstattdaten lassen die
offene Aufnahmefrage bestehen.

Die Pflichtfelder der normalen Aufnahme bleiben bestehen. Bei unbekanntem
Baujahr nennt der Assistent die Fahrzeugunterlagen und die bereits akzeptierte
Erstzulassung als Alternative. Der Name bleibt optional; beim Kostenvoranschlag
ist das Baujahr weiterhin optional. Ob weitere Pflichtfelder übersprungen
werden dürfen, bleibt eine Produktentscheidung. Wiederholtes Nichtwissen führt
zu einer Erklärung und dem Angebot, später fortzufahren oder abzubrechen.

Lokale Regressionstests stehen in `tests/test_intake_regressions.py`. Sie
prüfen gespeicherte Tickets und beide Kanalvarianten, außerdem den öffentlichen
Webchat und signierte Meta-Webhooks mit simuliertem Versand. Bestehende
Zugriffs-, Übergabe- und WhatsApp-Tests bleiben Teil des vollständigen Laufs:

```text
python -m unittest discover -s tests -p "test_intake_regressions.py" -q
python -m unittest discover -s tests -p "test_*.py" -q
```

Für die Prüfung nach dem Deployment in beiden Kanälen mit eigenen Testkontakten:

1. Zwei Meldungen in derselben Sitzung abschließen und beide gespeicherten
   Datensätze prüfen: verschiedene IDs, erstes Ticket unverändert.
2. Fahrzeug und Telefonnummer während der Aufnahme korrigieren und anschließend
   die gespeicherten Werte kontrollieren.
3. Kostenvoranschlag am Telefon- und Namensschritt abbrechen: kein neues Ticket.
4. Ölwechsel mit Telefonnummer in der ersten Nachricht sowie die vier Formate
   `8500`, `8.500`, `8500 km`, `8.500 km` testen.
5. Öffnungszeiten als Nebenfrage, unbekanntes Baujahr und eine echte Statusfrage
   prüfen; ein fremder Kontakt darf keine Ticketdaten erhalten.

Diese lokalen Tests ersetzen keine Online-Prüfung oder Prüfung mit PostgreSQL.
Die Gesprächskorrekturen erfordern keine Änderung des Datenbankschemas.

## Versand und gleichzeitige Bearbeitung

Manuelle Nachrichten werden vor dem HTTP-Aufruf mit einer stabilen ID reserviert,
im Ticket als `pending` protokolliert und die Automatik wird pausiert. Der gleiche
Versuch mit gleicher ID sendet nicht doppelt. Ein identischer bereits erfolgreicher
Formularversuch zeigt seinen gespeicherten Erfolg auch dann, wenn seine Frage
inzwischen geschlossen oder das Sendefenster abgelaufen ist. Geänderter Inhalt,
Empfänger, Zweck oder explizites Antwortziel mit derselben ID werden abgewiesen.
Die Auswahl einer offenen Frage bleibt für neue Antworten verpflichtend.
Aufträge an Meta verwenden weiterhin
die serverseitige 24-Stunden-Prüfung; genehmigte Startvorlagen bleiben ausgenommen.

Bei Erfolg wird die Nachricht `sent`; erst dann löst eine Werkstattantwort ihre
Frage. Bei einem eindeutigen Fehler bleibt sie als `failed` sichtbar und löst
keine Frage. Der vorherige Gesprächszustand wird nur wiederhergestellt, wenn
zwischenzeitlich keine neuere Aktion oder Kundenantwort erfolgte. Bei unklarem
Transportstatus bleibt `unknown`; es wird nicht automatisch erneut gesendet.
Eine zuordenbare spätere Meta-Erfolgsbestätigung kann die Frageauflösung nachholen.

Seit der gezielten Ergänzung vom 28. September behalten definitive Fehler ihren
eigenen Versuch; „Erneut senden“ erzeugt erst beim bewussten Absenden eine neue ID.
Unklare neue Versuche bleiben reserviert. Nach fünf Minuten kann ein angemeldeter
Werkstattnutzer den tatsächlichen Meta-Status prüfen und ausdrücklich bestätigen.
Details, Sicherheitsgrenzen und aktuelle Prüfergebnisse stehen in
[Versandkorrekturen vom 28. September](versandkorrekturen-2026-09-28.md).

Ein laufender Versand blockiert weitere Sendungen im selben Gespräch und die
erneute Aktivierung der Automatik. SQLite schützt die Änderungen mit einer
Transaktion; PostgreSQL nutzt zusätzlich eine kurze Transaktionssperre je
Werkstatt. Während HTTP-Anfragen bleibt keine Datenbanktransaktion offen.

## Additive Migration

`init_db()` ergänzt Gesprächszustände, die ausstehende Werkstattfrage für
unzugeordnete WhatsApp-Gespräche und eine eindeutige interne WhatsApp-Nachrichten-ID.
Ticketnotizen bekommen ihre Metadaten additiv. Wiederholtes Ausführen erhält IDs
und vorhandene Zuordnungen. Die Migration verwendet die vorhandenen SQLite- und
PostgreSQL-Muster.

- Alte Kundenfragen bleiben offen, solange kein belegbarer Abschluss vorliegt.
- Eine historische `customer_reply` wird ohne gesicherte Bedeutung als
  Werkstattinformation mit `legacy_semantics_uncertain` lesbar gehalten. Daraus
  wird keine konkrete Frage-Antwort-Verknüpfung erfunden.
- War eine frühere Kundenfrage bereits im alten Aggregat geschlossen und lag
  danach eine alte Werkstattnachricht vor, bleibt dieser historische Stand als
  `legacy_closed` und `legacy_resolution_uncertain` gekennzeichnet. Die Oberfläche
  nennt ihn „Früher als erledigt markiert“. Das ist kein Nachweis einer bestimmten
  beantwortenden Nachricht; `resolved_at` und `reply_to_message_id` werden dafür
  nicht erfunden.
- Nicht interpretierbare historische JSON-Inhalte bleiben bei der Migration
  unverändert. Tickets, Nachrichten, Werkstatt- und Telefonverknüpfungen werden
  nicht gelöscht.

Vor dem produktiven Einspielen Datenbank sichern, neue Version während einer
kurzen Wartungsphase starten und den Migrationslauf kontrollieren. Eine ältere
Anwendungsversion soll anschließend nicht gleichzeitig schreiben, weil sie die
neuen semantischen Metadaten nicht kennt.

## Verifikation und Grenzen

### Geänderte Bereiche

| Dateien | Änderung |
| --- | --- |
| `app/communication.py`, `app/tickets.py`, `app/db.py` | Semantik, abgeleitete offene Fragen, Zustände, gezielte Auflösung und additive Migration |
| `app/manual_dispatch.py`, `app/customer_handoff.py`, `app/main.py`, `app/whatsapp.py` | Reservierter Versand, Kundenantworten, Zustandsprüfung vor Intake, Webhooks und Versandrückmeldungen |
| `app/conversation/existing_ticket.py`, `general_question.py`, `intent.py`, `router.py` | Gespeicherte Fakten, Werkstattentscheidungen und eindeutiger Ticketkontext |
| `app/web.py` | Formularverarbeitung, sichere Antwortziele, explizite Rückgabe und Anzeige-Kontext |
| `templates/ticket.html`, `whatsapp.html`, `dashboard.html`, `chat.html`, `_communication.html`, `_communication_script.html` | Zweck-/Zielauswahl, Verlauf, Gesprächszustand und Wiederholschutz |
| `tests/test_communication_*.py`, `test_communication_composer.mjs` | Neue Modell-, Migrations-, Routing-, Transport-, Formular- und Oberflächentests |
| `tests/test_conversation_flows.py`, `test_customer_authorization.py`, `test_web_session_security.py` | Bestehende Regressionen an die geforderte Semantik angepasst |

### Ausgeführte Prüfungen der ursprünglichen Kommunikationsüberarbeitung

Abschluss am 26. September 2026:

- Python-Gesamtlauf: 292 Testfälle, 291 bestanden und der optionale PostgreSQL-Test
  ohne Datenbank-URL erwartungsgemäß übersprungen (236,993 Sekunden).
- Derselbe PostgreSQL-Integrationstest separat mit einer entbehrlichen
  PostgreSQL-18-Datenbank bestanden, einschließlich Wiederholungsmigration.
- 10 JavaScript-Tests bestanden: sieben Composer- und drei Worker-Regressionen.
- Ticket, WhatsApp-Posteingang und Kontaktmodal auf Desktop sowie bei 390 Pixeln
  Breite visuell geprüft; kein horizontaler Überlauf. Alle vier HTML-Seiten
  einschließlich Kundenchat gerendert und deren JavaScript-Syntax geprüft.
- `git diff --check` ohne Fehler. Ein begrenzter Secret-Musterscan der geänderten
  Textdateien ergab keine Treffer.

Die Regressionstests stehen in `tests/test_communication_*.py`, die Composer-Tests
in `tests/test_communication_composer.mjs`. Sie prüfen unter anderem Zuordnung,
Frageauflösung, manuelle Übergabe, Parallelversand, Fehlerwiederholung, Legacy-Daten,
Mandantentrennung und die gerenderten Formulare. Zusätzlich wurde die additive
Migration tatsächlich mit PostgreSQL 18, Python 3.12 und psycopg 3.2.3 in einer
isolierten Testumgebung ausgeführt. Der PostgreSQL-Test benötigt eine ausdrücklich
als Testdatenbank konfigurierte, entbehrliche Datenbank
(`WERKSTATTAI_TEST_POSTGRES_URL`); er verändert deren Schema zum Testen des Upgrades.

Die Klassifikation ist bewusst regelbasiert: Unklare Fragen gehen an die Werkstatt.
Ein nach Prozessabbruch unklarer Versand muss anhand des tatsächlichen Zustellstands
geprüft werden; ohne diesen Nachweis gibt es keine automatische Wiederholung oder
Freigabe einer hängen gebliebenen Versandreservierung. Der Kundenwebchat lädt
Werkstattnachrichten zusätzlich etwa alle zehn Sekunden über `/chat/messages`.
Die Abfrage ist an die signierte Browseridentität und die zugehörige Sitzung
gebunden, gibt keine internen Notizen zurück und erzeugt keine Gesprächseinträge.
Ausgeblendete Seiten und laufende Sendungen pausieren das Polling; Fehler und
Rate-Limits führen zu längeren Wiederholungsabständen. Nachrichten-IDs verhindern
doppelte Anzeige. Antworten einer alten Sitzung werden nach „Neu starten“ verworfen.
Reale Meta-Sendungen, eine Migration der Produktivdatenbank und ein Live-Deployment
sind nicht Teil dieser lokalen Verifikation.
