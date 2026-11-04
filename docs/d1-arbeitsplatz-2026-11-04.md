# D1 – Dashboard und Ticketansicht vom 4. November 2026

Der von Mikołaj bestätigte Entwurf wurde in die vorhandenen Jinja-Ansichten
übertragen. Grundlage ist der geprüfte `master` auf
`63a6e42cec8daa1ce602f8678f98d2d9bb95aabf`. Der Produktcode dieses Ausgangspunkts
entspricht dem bisherigen Produktionsstand `4eb8e3899314dc12d4af1d60fb0cf7b42e093b32`;
die zwei zusätzlichen Änderungen betreffen Dokumentation.

## Ergebnis

- Dunkle Markenzeile, horizontale Navigation, Inter und ein gemeinsames
  visuelles System für aktive Tickets, Archiv und Ticketdetails.
- Getrennte Ticketkarten mit dauerhaftem, auswählbarem Fallüberblick.
  Die Auswahl und Listenposition bleiben beim Wechsel in die Details erhalten.
- Fahrzeugkarte mit hervorgehobenem Baujahr und Kilometerstand, derselben
  Illustration wie im Entwurf sowie getrennten Angaben zu Fahrbereitschaft
  und Abschleppdienst. Fehlende Angaben bleiben ausdrücklich unbekannt;
  `0` Kilometer wird als `0 km` angezeigt. Keine erfundenen Fahrzeugfelder.
- Chronologisches Gespräch mit klaren Absendern und den Bereichen Gespräch,
  Interne Notizen und Falldaten. „Antworten“ wählt eine konkrete offene Frage
  im bestehenden Formular, ohne selbst etwas zu versenden.
- Die Versandanzeige übernimmt den tatsächlichen Status des verknüpften
  WhatsApp-Eintrags. Übergabe an Meta, Zustellung und Lesen bleiben getrennt;
  bloßes Speichern im Webchat wird nicht als Meta-Zustellung bezeichnet.

[Freigegebener Figma-Entwurf](https://www.figma.com/design/Lah6WK5TUcrf3fLHFmexff/WerkstattAI-Dashboard-und-Ticket).
Die Figma-MCP-Werkzeuge waren in dieser Sitzung nicht verfügbar. Verwendet
wurden die ursprünglichen Entwurfsquellen, die aktualisierten Fahrzeugkarten
und die bereits im tatsächlichen Figma-Editor kontrollierten Ansichten.

## Bestehende Funktionen

Alle acht Navigationseinstiege einschließlich rollenabhängigem Admin und
POST-Abmeldung bleiben bestehen. Kennzahlen, zusätzliche Kennzahlen,
Aufgabenhinweise, Suche, Filter, Sortierung und Seitenwechsel sind weiter
erreichbar. `kundenfragen_offen` heißt in der Anzeige „Antwort erforderlich“;
der Schlüssel und das getrennte Warten auf eine Kundenantwort bleiben bestehen.

Formularziele, Feldnamen, Ticket- und Werkstattkennung, Listenrücksprung,
Schnellansicht, Kopieren, Telefonlinks, Statuswechsel und Archivierung mit
Bestätigung sind erhalten. Nachrichten verwenden weiterhin den vorhandenen
Composer mit Zweck, Fragebezug, Entwurf und Wiederaufnahme. Übernahme der
Unterhaltung, Versandklärung, blockierter Freitext, separates Starttemplate,
geschützte Bilder und technische Rohdaten bleiben zugänglich.

Die Live-Aktualisierung berücksichtigt die neue Vorschau und erneuert nach
einem Statuswechsel auch die Archivierungsaktion. Der Gesprächsverlauf bewahrt
beim Erneuern seine Scrollposition beziehungsweise folgt am bisherigen Ende.

Keine Datenbankmigration und keine Änderung der Geschäftsregeln, Meta-Zugänge
oder Coexistence-Freigabe. Nur der Ressourcenordner `static/arbeitsplatz` wird
öffentlich ausgeliefert; das Repository und geschützte Kundenmedien nicht.
Die bestehende Content Security Policy bleibt unverändert.

## Prüfung

- Vollständiger abschließender Python-Lauf: **767 Tests, ohne Fehler**, davon
  90 mangels gesonderter PostgreSQL-Testdatenbank übersprungen
  (677 tatsächlich ausgeführt), 531,012 Sekunden. Der vorherige Lauf mit
  den 761 vorhandenen Tests war ebenfalls ohne Fehler, mit denselben 90
  übersprungenen Fällen.
- **62/62 JavaScript-Tests** bestanden; Syntax des neuen Oberflächenskripts
  geprüft, `git diff --check` ohne Befund.
- Die sechs zusätzlichen Python-Tests prüfen Formularziele, Rücksprung und
  Rollen, chronologischen Verlauf und getrennte Notizen, echte Fahrzeugdaten
  einschließlich Null/fehlender Werte und HTML-Escaping, statische Ressourcen
  mit bestehenden Schutzheadern sowie tatsächliche Versandstatusanzeigen.

Browserprüfung mit ausschließlich erfundenen lokalen Daten: Auswahl eines
Tickets, Status aus der Vorschau einschließlich Zählern und Rückmeldung,
Status im Detail mit anschließender Archivierungsaktion, interne Notiz,
gezielte Antwort im Webchat, Rückkehr zur ausgewählten Karte, Schnellansicht,
WhatsApp-Formular und blockierter Versand, Register und Falldaten.
Desktop und schmale Darstellung wurden ohne horizontales Seitenüberlaufen
betrachtet. Lokale Bildschirmnachweise liegen in `artifacts/` und werden
zusammen mit Testdaten und Logs weder nach Git noch ins Image aufgenommen.

Es wurde keine Nachricht an einen echten Kunden gesendet. PostgreSQL-Tests
benötigen eine gesonderte entbehrliche Testdatenbank; Produktionsdaten werden
nicht als Testdatenbank verwendet. Ein angemeldeter Produktionstest und die
tatsächlich aktivierte Deployment-Version sind eigene Nachweise.

## Veröffentlichung und Rückweg

Railway ist unverändert mit `codex/kundenkommunikation-2026-09-26` und
aktivem Auto-Deploy verbunden. Der geprüfte Änderungsstand wird zuerst auf
der D1-Aufgabenbranch veröffentlicht und mit `master` zusammengeführt. Anschließend
wird die bisherige Produktionsbranch ohne Force-Push auf denselben geprüften
Stand vorgezogen. Die Railway-Konfiguration bleibt dabei erhalten.

Bei einer bestätigten Regression kann der D1-Commit durch einen normalen
Revert-Commit zurückgenommen und über dieselbe Produktionsbranch neu
bereitgestellt werden. Der vorherige Produktcode bleibt in `4eb8e38`
nachvollziehbar. Eine Datenbankrücksicherung ist für diesen reinen
Oberflächenwechsel nicht vorgesehen. Kein vorsorglicher Rollback.

D1 bleibt als Gesamtpaket offen: Login, eigenständige WhatsApp-Unterhaltungen
und Kundenchat sind nach diesem Dashboard-/Ticketschritt weiter zu gestalten.
