# D1: Operativer Oberflächenentwurf und Bestandsabgleich

Stand: 3. November 2026. Referenz: `master` auf
`63a6e42cec8daa1ce602f8678f98d2d9bb95aabf`.

Mikołaj hat die Entwurfsrichtung „Operacyjny“ ausgewählt: eine klare Anfragequeue,
Fahrzeugillustration, erkennbare WhatsApp-Marke und eine moderne, ruhige Oberfläche.
Der überarbeitete Entwurf berücksichtigt nun die bestehenden Navigationspunkte,
Felder und Kommunikationsaktionen. Die konkrete neue Fassung steht zur Bewertung.

## Ergebnis und Geltungsbereich

Ein interaktiver Entwurf im Beraterchat wurde mit ausschließlich fiktiven Daten
erstellt. Es ist keine in die FastAPI-/Jinja-Anwendung integrierte Implementierung.
Aus den geprüften Schnittstellen folgt ein konkreter Integrationsplan, jedoch noch
kein Nachweis der technischen Kompatibilität oder einer produktiven UI-Abnahme.

Keine Änderungen an Produktcode, Datenbank, Meta, Versandkonfiguration oder
Produktionsdeployment. Kein echter Kundenkontakt. Die reale Coexistence-Freigabe
bleibt unverändert. Figma und eine kostenpflichtige Figma-Subskription waren für
diese Entwurfsrunde nicht erforderlich.

Ein angemeldeter Live-Abgleich war in dieser Runde nicht möglich: die neue
App-Karte zeigte die reguläre Anmeldung. Die nachfolgende Bestandsaufnahme
stützt sich auf den aktuellen GitHub-Quellcode und die D1-/Projektnotizen.

## Navigation

| Bestehender Bereich | Bestehender Pfad | Entwurf |
| --- | --- | --- |
| Tickets und Aufgaben | `/dashboard` | Queue und Schnellansicht |
| WhatsApp | `/dashboard/whatsapp` | Eigene Inbox und Gespräch |
| Direktannahme | `/dashboard/intake` | Bestehende Felder im lokalen Beispiel |
| Archiv | `/dashboard/archive` | Eigene archivierte Auswahl |
| Einstellungen | `/dashboard/settings` | Navigationspunkt erhalten; Detailgestaltung offen |
| Abo | `/dashboard/billing` | Navigationspunkt erhalten; Detailgestaltung offen |
| Admin | `/dashboard/admin/workshops` | Nur in der Administratorperspektive |
| Abmelden | `POST /logout` | Im Entwurf ausschließlich lokaler Hinweis |

Die letzten drei Verwaltungsbereiche wurden nicht als neue funktionale Seiten
nachgebaut. Die Vorschau benennt diese Grenze ausdrücklich. Die bestehende
Berechtigungsprüfung muss bei der Integration maßgeblich bleiben.

## Datenvertrag für Fahrzeug und Ticket

Verwendete bestehende Felder: `fahrzeug`, `baujahr`, `kilometerstand`,
`fahrbereit`, `abschleppdienst`, `kunde_name`/`name`, `telefon`, `problem`,
`ticket_view_id`, `source`, `priority`, `request_type`, `status_ui`,
`conversation_state` und die vorhandenen Kommunikationsdaten.

Motorisierung, Getriebe und Kennzeichen aus dem vorherigen freien Entwurf werden
nicht als verfügbare Produktfelder vorausgesetzt. Fehlende Fahrzeugangaben bleiben
als fehlend erkennbar. Die Illustration ist weiterhin ein ausdrücklich markiertes
Symbolbild; eine automatische Zuordnung von Modell/Generation wurde nicht gebaut.

## Filter und Kennzahlen

Die bestehenden Query-Schlüssel bleiben für die Integration unverändert:
`workshop_id`, `q`, `status`, `source`, `metric`, `task_state`, `question_state`,
`sort`, `page` und `limit`. `return_to` muss den gefilterten Listenkontext bewahren.

- Statuswerte: `offen`, `in_bearbeitung`, `erledigt`; Archivbestand separat.
- Quellen: `whatsapp`, `web_chat`, `direktannahme`.
- Aufgaben: `all`, `pending`, `information`, `waiting`.
- Kundenfragen: `all`, `open`, `answered`.
- Sortierung: `newest`, `oldest`, `updated`, `priority`.
- Hauptkennzahlen: Offen, In Bearbeitung, Antwort erforderlich, Hohe Priorität.
- Weitere Kennzahlen: Gesamt, Erledigt, Notfälle, Kundeninformationen,
  Kostenvoranschläge; Arbeitsübersicht und Warten auf Kundenantwort erhalten.

„Antwort erforderlich“ ist ausschließlich die neue sichtbare Bezeichnung für
`kundenfragen_offen`. Der bestehende Zähler und seine fachliche Bedeutung werden
dadurch nicht geändert. Kennzahlen zählen weiterhin den gesamten jeweiligen
Bereich, unabhängig von den sichtbaren Listenfiltern.

## Aktionen und vorhandene Bindungen

| Aktion | Bestehender Vertrag |
| --- | --- |
| Ticket/Schnellansicht | `ticket_view_id`, `details_json`, bestehender Listenkontext |
| Status speichern | `POST /dashboard/ticket/{ticket_id}/status` bzw. `/status_quick`; `status`, `workshop_id`, `return_to` |
| Archivieren | `POST /dashboard/ticket/{ticket_id}/archive`; nur für erledigte Tickets, Bestätigung beibehalten |
| Interne Notiz | `POST /dashboard/ticket/{ticket_id}/notes`; `note_type=internal_note`, `note_text` |
| Kundenantwort aus Ticket | Derselbe Notes-Endpunkt mit `note_type=customer_reply`, `purpose` und ggf. `reply_to_message_id` |
| WhatsApp-Inbox-Antwort | `POST /dashboard/whatsapp/reply`; bestehende Empfänger-, Ticket-, Kontext- und Nachrichten-ID-Felder |
| Gesprächsführung WhatsApp | `POST /dashboard/whatsapp/control`; `mode=manual/assistant` und vorhandene Kontextfelder |
| Gesprächsführung Webchat | `POST /dashboard/ticket/{ticket_id}/conversation-control`; vorhandener `state` |
| Kundeninformation bearbeiten | `POST /dashboard/ticket/{ticket_id}/information-resolve`; `message_id` |
| Startvorlage | `POST /dashboard/whatsapp/start-template`; eigener Vorgang, kein Freitext-Workaround |
| Unklaren Versand klären | `POST /dashboard/whatsapp/messages/{message_id}/resolve`; vorhandene Bestätigung und Sperrbedingungen |
| Bilder anzeigen | Authentifizierter Medienpfad `/dashboard/whatsapp/medien/{nachrichten_id}` |
| Direktannahme | `POST /dashboard/intake`; bestehende Pflicht-/Optionalfelder und Grenzen |

## Gestaltung des Gesprächs

Nachrichten werden in zeitlicher Reihenfolge gezeigt. Kunde links, Werkstatt und
Assistent rechts; der Absender bleibt ausdrücklich lesbar. Eine warme, dezente
Fläche und kompakte Blasen schaffen einen vertrauteren Gesprächseindruck.

Fragen, Kundeninformationen und interne Notizen bleiben fachlich getrennt.
Der Entwurf zeigt eine Antwort direkt mit ihrem Bezugsinhalt. Die bestehende
Pflicht zur Auswahl von `purpose` und beim Antworten von `reply_to_message_id`
bleibt erhalten. Die drei Werkstattzwecke heißen weiterhin `workshop_answer`,
`workshop_question` und `workshop_notification`.

Bearbeitungsstatus und Gesprächszustand sind getrennte Anzeigen. „Erledigt“
beantwortet keine Kundenfrage und erteilt keine Abholfreigabe. Interne Notizen
erhalten einen eigenen Bereich und erscheinen nicht als Kundenantwort.

`sent` bedeutet „An Meta übergeben“, `delivered` bedeutet „Zugestellt“, `read`
bedeutet „Gelesen“. Ein einzelnes Häkchen darf nicht als Zustellung ausgegeben
werden. `pending`, `unknown`, `failed`, Servicefenster, Empfänger und Readiness
bleiben maßgeblich. Eine Startvorlage öffnet das Freitextfenster nicht selbst.

## Implementierungsgrenzen

Die Vorschau verwendet lokales Beispiel-JavaScript; dieses ersetzt keine
Produktlogik. Bei der Umsetzung die vorhandenen Jinja-Formulare, `name`-Attribute,
versteckten IDs, Routing- und Berechtigungsprüfungen weiterverwenden. Bestehende
DOM-Anker und `data-*`-Verträge zunächst behalten, darunter Kommunikation,
Nachrichtenbezug, Versandwiederherstellung, Entwürfe und Listenrückkehr.

`_dashboard_events.html`, `_dashboard_live_script.html`, `_chat_polling_script.html`
und die Medien-/Dispatch-Komponenten müssen mit dem neuen DOM kontrolliert werden.
Ein Layoutwechsel zu chronologischen Blasen erfordert einen Abgleich der vorhandenen
Sortierung, ohne die kanonischen Nachrichten oder Zeitstempel umzuschreiben.
Technische Details und vorhandene Raw-Daten-Ansichten bleiben bei einer Integration
erreichbar; die Vorschau zeigt davon nur einen begrenzten Ausschnitt.

## Tatsächlich geprüft

- Aktueller GitHub-Commit und Quelltexte von Dashboard, Ticket, WhatsApp,
  Direktannahme, Kommunikationsmakros sowie den relevanten Python-Funktionen.
- Syntaxprüfung des Vorschau-JavaScripts erfolgreich.
- Im lokalen Browser: Ticket öffnen, konkrete Frage beantworten, Frage danach
  beantwortet und neue Werkstattnachricht als „An Meta übergeben“ angezeigt.
- Interne Notiz separat gespeichert; Beispielanhang sichtbar; Kundeninformation
  einzeln bearbeitet; Status ausdrücklich gespeichert.
- Suchbegriff nach Ticketöffnung und Listenrückkehr erhalten.
- Geschlossenes WhatsApp-Fenster sperrt Freitext. Simulierte Startvorlage lässt
  das Fenster geschlossen.
- Direktannahme mit Pflichtfeldern lokal erstellt, auf erledigt gesetzt und nach
  Bestätigung ausschließlich im Vorschauarchiv angezeigt.
- Desktopdarstellung bei 1024 und Mobilansicht bei 320 Pixeln kontrolliert;
  Gespräch ohne horizontalen Inhaltsüberlauf, Bilder und Markenasset geladen.

Keine neue vollständige Produktregression und kein Test mit echter Meta-Zustellung.
Die Wiederherstellung eines unklaren Versands ist als Entwurfszustand enthalten;
eine erneute Backend-Abnahme dieses Pfads wurde nicht durchgeführt.

## Nächster Schritt

Mikołaj bewertet die konkrete überarbeitete Navigation, das Gespräch und die
Fahrzeugkarte. Danach den bestätigten Entwurf in der vorhandenen Anwendung auf
einer eigenen D1-Branch umsetzen und die betroffenen Funktionspfade mit W1 prüfen.

## Quellen

- [Dashboard](https://github.com/WerkstattAI/WerkstattAI/blob/63a6e42cec8daa1ce602f8678f98d2d9bb95aabf/templates/dashboard.html)
- [Ticket](https://github.com/WerkstattAI/WerkstattAI/blob/63a6e42cec8daa1ce602f8678f98d2d9bb95aabf/templates/ticket.html)
- [WhatsApp](https://github.com/WerkstattAI/WerkstattAI/blob/63a6e42cec8daa1ce602f8678f98d2d9bb95aabf/templates/whatsapp.html)
- [Kommunikationsmakros](https://github.com/WerkstattAI/WerkstattAI/blob/63a6e42cec8daa1ce602f8678f98d2d9bb95aabf/templates/_communication.html)
- [Routen und Kennzahlen](https://github.com/WerkstattAI/WerkstattAI/blob/63a6e42cec8daa1ce602f8678f98d2d9bb95aabf/app/web.py)
- [D1 in Notion](https://app.notion.com/p/3fffa727c11d812fafd8fd9b69b5091f)

