# M2: Werkstattnummer mit WhatsApp Business weiterverwenden

Prüfdatum: 26. Oktober 2026. **Ergebnis: technisch vorgesehen über Coexistence,
in WerkstattAI aber noch nicht anschlussbereit.** M1 bestätigt den eigenen
Cloud-API-Testzugang; es bestätigt keinen angeschlossenen externen Betrieb.

## Grundlage und Grenzen

- Quellstand: `aa965e481f62ad34ee752d5b3cd89f365c4d30fb`, weiterhin Head von
  `codex/kundenkommunikation-2026-09-26`. Der Berichtsstand
  `3cf038b76bfc007fa3c55a6054e5898016d3ab74` unterscheidet sich davon nur in
  Dokumentation und Projektanweisungen. Lokaler Arbeitsbaum sauber auf
  `codex/m1-whatsapp-pruefung-2026-10-21`; keine Produktänderungen.
- Angemeldete Meta-App, ihre Berechtigungen, Login-Konfigurationen und
  Webhook-Felder wurden aktuell gelesen. Keine Verträge angenommen,
  Freigaben beantragt, Telefonnummern verbunden oder Nachrichten versendet.
- Ein konkretes Kundenkonto und dessen Nummer wurden nicht freigegeben oder
  auf Eignung geprüft. Kein neuer vollständiger Produktions- oder Sicherheitstest.
- Aktuelle Primärquellen wurden im angemeldeten Browser gelesen; der
  öffentliche Textabruf der Meta-Dokumentation lieferte teilweise HTTP 429.

## 1. Meta und Freigaben

Aktuell beobachtet:

| Bereich | Befund | Erforderliche Fortsetzung |
| --- | --- | --- |
| WhatsApp-Berechtigungen | `whatsapp_business_management` und `whatsapp_business_messaging`: „Bereit zum Testen“ | Advanced Access für die Betreuung fremder Geschäftskonten über App Review nachweisen. |
| Tech Provider | Der Assistent bietet weiterhin den Start als unabhängiger Anbieter oder mit Lösungspartner an. Nicht gestartet. | Anbieter-Onboarding abschließen; nächste Schritte anhand des jeweiligen Kontostatus prüfen. |
| Unternehmensverifizierung | „Nächste Schritte“ meldet „Nicht gestartet“. | Für den eigenen Tech-Provider-Prozess Unternehmensverifizierung abschließen. Die optionale Empfehlung im allgemeinen Cloud-API-Einstieg ersetzt diese Anbieteranforderung nicht. |
| Facebook Login for Business | Keine bestehende Konfiguration angezeigt, nur Erstellen/mit Vorlage erstellen. | Embedded-Signup-Konfiguration für Cloud API und Business-App-Onboarding einrichten. |
| Webhook-Felder | `messages` und `account_update` aktiv; `history`, `smb_app_state_sync`, `smb_message_echoes` deaktiviert | Zuerst passende Verarbeitung implementieren, danach Felder und Abonnement des jeweiligen Kundenkontos aktivieren. |

Die [aktuelle Tech-Provider-Anleitung](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers)
verlangt Unternehmensverifizierung und App Review mit den beiden erweiterten
WhatsApp-Berechtigungen. Dazu gehören prüfbare App-Einstellungen und
Videobelege für Versand/Empfang und Vorlagenerstellung. Das Vorhandensein eines
gültigen eigenen Tokens oder einer Live-App reicht als externer Zugang nicht aus.
Die Unterlagen und URLs für App Review sind vor Einreichung abzugleichen;
deren vollständige Aktualität wurde hier nicht erneut geprüft.

## 2. Fehlende Umsetzung in WerkstattAI

| Priorität | Fehlende Funktion | Konkreter Quellnachweis |
| --- | --- | --- |
| P0 | Autorisierter Verbindungsprozess für den angemeldeten Werkstattinhaber | Keine Embedded-Signup-/OAuth-Implementierung in `app/` oder `templates/`. `app/web.py:2040` speichert eine manuell eingegebene Nummern-ID; das ist keine Meta-Autorisierung. |
| P0 | Kundenspezifische Konto-/Nummernzuordnung und sicherer Tokenbezug | `app/db.py:223` speichert bisher Nummern-ID/Anzeigenummer. Kein Verbindungsmodell mit Messaging-Konto, Freigaben und Lebenszyklus. `app/config.py:38` sowie Versand und Medienabruf verwenden einen globalen Zugang. |
| P0 | Antwort aus der Business-App einmal im Verlauf speichern und Automatik anhalten | `app/whatsapp.py:82,137` liest nur `value.messages` und `value.statuses`; kein `value.message_echoes`. `app/main.py:389` verwendet nur diese beiden Parser. Ein Mitarbeitertext vom Telefon hat damit keine Übernahmewirkung in WerkstattAI. |
| P0 | Vertrauenswürdige, eindeutige Bindung einer Nummer an genau eine Werkstatt | `app/workshops.py:98` und der gemeinsame Sender lehnen mehrdeutige Zuordnung ab. Die Speicherwege in `app/workshops.py:118` und `app/admin.py:127` verhindern doppelte Nummern-IDs jedoch nicht; kein entsprechender Unique-Index. Rohes Bearbeiten einer Nummern-ID muss durch den autorisierten Verbindungsprozess begrenzt werden. |
| P0 | Abmeldung und Berechtigungsverlust berücksichtigen | Kein Handler für `account_update` und keine Verbindungsstatusverwaltung; aktives App-Abonnement allein verarbeitet keine Kontolebenszyklen. |
| P0 beim Onboarding | Synchronisierung und historische Daten getrennt verarbeiten | Keine Handler für `history` und `smb_app_state_sync`; Auswahl des Kunden respektieren, Fortschritt/Fehler erfassen und keine historischen Nachrichten als neue Arbeitsaufträge behandeln. |
| Vor echtem Betrieb | Versandvorlagen und tatsächliche Abrechnung je Kundenkonto | Die Startvorlage ist global konfiguriert (`app/config.py:41`). Verfügbarkeit, Sprache und Genehmigung im Kundenkonto prüfen; Zahlungsweg nach gewähltem Anbieterprozess einrichten. |

Vorhandene Basis bleibt nutzbar: signierte Webhooks, werkstattspezifische
Gespräche/Tickets, manueller Gesprächsmodus, Versandstatus, Wiederholungsschutz,
geschützte Medien sowie Ablehnung einer mehrdeutigen Senderzuordnung.
Es fehlt die Verbindung und Synchronisierung für unabhängige Kunden,
nicht der gesamte Nachrichtenkern.

### Gezielte Reproduktion ohne Datenbank oder Netzwerk

Die tatsächlichen Parser wurden aus dem lokalen Originalquelltext mittels AST
isoliert und mit drei synthetischen Payloads aufgerufen:

| Payload | Als Eingang erkannt | Als Status erkannt |
| --- | --- | --- |
| Neue Textnachricht, Feld `messages` | 1 | 0 |
| Mitarbeiterantwort, Feld `smb_message_echoes`, Inhalt `message_echoes` | 0 | 0 |
| Historisches Medienereignis, Feld `history`, Inhalt `messages` | 1 | 0 |

Damit sind das fehlende Telefon-Echo und die fehlende Trennung nach
`change.field` belegt. Vor dem Einschalten zusätzlicher Abonnements muss ein
Dispatcher die Ereignisse zuordnen. Wiederholte, verspätete und parallele Echos
dürfen keine neue Kundenantwort auslösen oder eine bereits vorbereitete
Automatik unkontrolliert versenden. Ein Echo darf kein neues 24-Stunden-Fenster
eröffnen. Lokale Prüfarbeitsdateien bleiben außerhalb des Produkt-Repositorys.

## 3. Ablauf für den ersten Kunden

1. Berechtigten Inhaber, bereits verwendete WhatsApp Business-App, aktuelle
   Version (Meta nennt mindestens 2.24.17), Geräte und Eignung der konkreten
   Nummer im Meta-Flow prüfen. Die Nummer bleibt Eigentum des Kunden.
2. Der Inhaber startet im richtigen Werkstattkonto „WhatsApp verbinden“,
   autorisiert seine eigenen Assets und bestätigt die Verbindung in seiner
   Business-App. Die Verifikation kann per Code bzw. angebotener QR-Option
   erfolgen. Keine pauschale Aufforderung, das vorhandene App-Konto zu löschen.
3. Der Server tauscht den zurückgegebenen Code gegen das Kunden-Business-Token,
   prüft die Assets und bindet sie an das richtige Werkstattkonto. Die App wird
   beim Messaging-Konto des Kunden für Webhooks abonniert.
4. **Für Coexistence den gewöhnlichen Register-Schritt überspringen.**
   Die Nummer ist bereits registriert. Das M1-Verfahren zur Wiederregistrierung
   einer abgemeldeten Testnummer ist kein Kunden-Onboarding-Verfahren.
5. Den vom Kunden gewählten Kontakt-/Verlaufsabgleich zeitnah abarbeiten.
   Meta nennt dafür ein Zeitfenster von 24 Stunden nach dem Onboarding.
   Ablehnung der Verlaufsfreigabe korrekt behandeln; keine automatische
   Kundenannahme oder Reparaturentscheidung aus importierten Chats erzeugen.
6. Mit freigegebenen Testkontakten Versand aus Dashboard und Telefon,
   Spiegelung, Mitarbeiterübernahme, Duplikate, Medien, Verbindungsabbruch
   und zwei getrennte Werkstattkonten nachweisen. Erst dann Betrieb freigeben.

Die [Coexistence-Anleitung](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users)
beschreibt das Weiterverwenden derselben Nummer und der Business-App.
Sie nennt auch Einschränkungen: verknüpfte Geräte werden beim Anschluss
abgemeldet und müssen unterstützt neu verbunden werden; WhatsApp für Windows
und WearOS sind dort als nicht unterstützte Begleitclients aufgeführt.
Gruppen werden nicht synchronisiert. Die Business-App bleibt nutzbar, besitzt
aber nach Anschluss nicht durchgehend denselben Funktionsumfang.

Die API-Seite unterliegt weiterhin ihrem Kundenservice-Zeitfenster und
ihrer Preisgestaltung. Antworten aus der Business-App öffnen oder verlängern
kein API-Zeitfenster. Der Kunde benötigt den vorgesehenen Zahlungsweg für
API-Nutzung; die eigene Meta-Testnummer bildet dessen Abrechnung nicht ab.

## 4. Empfohlene Reihenfolge

- Parallel die eigenen Anbieter-/Unternehmensfreigaben vorbereiten und M2
  implementieren. Wartezeiten von Meta sind keine belastbare Lieferzusage.
- **M2.1:** Verbindungsmodell, eindeutige Nummernbindung, sicherer Tokenbezug,
  autorisierter Embedded-Signup-Ablauf und Lebenszyklus.
- **M2.2:** Ereignisverarbeitung für Telefon-Echos, Übernahme, Historie und
  Kontakte; danach die passenden Abonnements aktivieren.
- **M2.3:** Tatsächlicher Anschluss eines ausdrücklich autorisierten Betriebs,
  getrennte zweite Testwerkstatt und dokumentierter Abnahmeablauf.

Für eine neue Implementierung [Embedded Signup v4](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/version-4)
verwenden: Die offiziellen Seiten nennen den 15. Oktober 2026 als Ende von
v2/v3. v4 unterstützt Business-App-Onboarding; die konkrete Konfiguration
bestimmt Produkte und benötigte erweiterte Berechtigungen. Ein pauschales
Hinzufügen weiterer Berechtigungen ist kein Ersatz für diesen Abgleich.

Serverseitige Schritte:
[Onboarding als Tech Provider](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider).

**M2 bleibt offen.** Dieser Befund ist eine Vorprüfung und Umsetzungsgrundlage,
keine erfolgte Kundenverbindung oder Genehmigung durch Meta.
