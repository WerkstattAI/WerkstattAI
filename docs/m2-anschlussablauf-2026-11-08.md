# M2 – Ablauf für den ersten Werkstattanschluss

Stand: 8. November 2026. Grundlage ist Produktcommit
`4df08d32cdb0c8ea65d19790574a4aff3f82616c` (D2 veröffentlicht).
Dieser Bericht beschreibt den vorgesehenen Ablauf und offene Betriebsbedingungen.
Er bestätigt keinen realen Coexistence-Anschluss eines Kunden.

## Ergebnis und Abgrenzung

Die erste Einrichtung ist ein begleiteter Vorgang: Der Betreiber legt das
Werkstattkonto an; der berechtigte Werkstattinhaber autorisiert seinen eigenen
WhatsApp-Zugang. Die Business-App und die Nummer sollen erhalten bleiben.
Der erfolgreiche eigene Cloud-API-Test ist kein Nachweis dieses Kundenablaufs.

Am 8. November hat Mikołaj erneut bestätigt, dass das Gewerbe noch nicht
angemeldet wurde. Der Meta-Kontobefund vom 3. November (fehlende
Unternehmensverifizierung, Rechte nur zum Testen, keine bestätigte
Signup-Konfiguration) bleibt historisch und muss vor Einrichtung neu gelesen
werden. Aus der Gewerbe-Antwort folgt keine pauschale Aussage über sämtliche
zulässigen Meta-Testmöglichkeiten oder rechtlichen Voraussetzungen.

## Ablauf und Verantwortung

| Schritt | Werkstattinhaber | Betreiber / WerkstattAI | Nachweis vor Fortsetzung |
| --- | --- | --- | --- |
| 1. Eignung klären | Verwendete App, Nummer, berechtigte Person und Zugriff auf das Telefon bestätigen | Business-App, privates WhatsApp und bestehenden API-Anschluss unterscheiden; Eignung im aktuellen Meta-Verfahren prüfen | Konkrete Nummer und Berechtigung geklärt; keine Kontolöschung als Standardanweisung |
| 2. Werkstattkonto | Kontaktdaten, Leistungen, Öffnungszeiten und Antwortvorgaben liefern | Eigenes Konto unter Admin → Werkstätten anlegen; Anmeldung sicher übergeben, getrennte Werkstattzuordnung prüfen | Anmeldung im richtigen Werkstattkonto; keine Nutzung des gemeinsamen Demokontos |
| 3. Meta autorisieren | In Einstellungen → WhatsApp verbinden den Meta-Dialog selbst bedienen und Zugriff auf die eigenen Assets bestätigen | Passende öffentliche Login-Konfiguration und geschützte Serverkonfiguration bereitstellen | Tatsächlicher Abschluss des passenden Coexistence-Flows, nicht nur geschlossener Dialog |
| 4. Verbindung prüfen | Bei angezeigtem Fehler Rückmeldung geben | Code serverseitig tauschen, Berechtigungen und Nummer prüfen, Token verschlüsseln, Kontoabonnement bestätigen | Autorisierte Verbindung gehört genau zur vorgesehenen Werkstatt; Fehlerzustände nachvollziehbar |
| 5. Verlauf / Kontakte | Entscheidung über die angebotene Freigabe treffen | Importstatus und Zuordnung prüfen oder bewussten lokalen Verzicht dokumentieren | Keine Annahme vollständiger Historie; Kontakte und alte Nachrichten lösen keinen neuen Versand aus |
| 6. Gemeinsame Abnahme | Mit einem vereinbarten Testkontakt Nachrichten senden und Antworten am Telefon kontrollieren | Eingang, Ticketzuordnung, Foto, Dashboardantwort und Antwort aus der Business-App prüfen; Übergabe an Mitarbeiter und Assistenten kontrollieren | Keine doppelten Antworten; Status korrekt; keine fremden Werkstattdaten |
| 7. Betriebsfreigabe | Umfang und Ansprechpartner bestätigen | Erst nach belegtem Echo-/Synchronisierungsschutz die gesonderte Betriebsfreigabe planen und nachvollziehbar ausführen | Nachweis für genau dieses Konto und diese Nummer; keine pauschale Freigabe durch einen Planvermerk |

Das vorhandene Adminformular erstellt das Konto einschließlich Zugang; eine
automatisierte Selbstregistrierung oder ein E-Mail-Einladungsablauf wird hier
nicht zugesagt. Die sichere Übergabe des initialen Zugangs ist vor dem Pilot
organisatorisch festzulegen.

## Was der aktuelle Code tatsächlich vorsieht

- `app/web.py`: Kontoanlage ausschließlich über die Adminroute; Anzeige der
  getrennten Coexistence-Betriebsbereitschaft.
- `app/whatsapp_anschluss.py`: sitzungsgebundene Anschlussversuche mit
  Abschluss-, Abbruch-, Ablauf-, Teilfehler- und Überholt-Zuständen.
- `app/whatsapp_verbindungen.py`: werkstattbezogene Verbindung, verschlüsselter
  Zugang und Widerruf; Autorisierung allein setzt die Betriebsfreigabe nicht.
- `templates/whatsapp_verbinden.html`: Verbindung, Status, Fortsetzung des
  Abonnements und Synchronisierungsoptionen. Die Oberfläche beschreibt ein
  24-Stunden-Fenster für die einmalige Importanforderung; dies ist ein geprüfter
  Produkttext, keine heute erneut bestätigte Meta-Frist.
- Bis zur Freigabe werden neue Eingänge für solche Anschlüsse nicht automatisch
  bearbeitet. Zurückgehaltene Eingänge werden laut Produktablauf später nicht
  automatisch nachverarbeitet. Ein bewusster Verlaufsimport ist davon getrennt.

## Voraussetzungen, die vor dem Kundenanschluss nachzuweisen sind

1. Anbieterstatus, Unternehmensverifizierung und benötigte erweiterte
   WhatsApp-Berechtigungen im aktuellen Meta-Konto prüfen. Historische
   Checkliste: `whatsapp_business_management` und `whatsapp_business_messaging`.
2. Passende Embedded-Signup-Konfiguration für Business-App-Onboarding,
   erlaubte Domain und Rückgabeparameter mit aktuellem Meta-Stand abgleichen.
3. App-ID, Login-Konfigurations-ID, zulässiger Ursprung, App-Secret und
   Verschlüsselungsschlüssel müssen auf Betreiberseite passend eingerichtet
   sein; diese Werte werden nicht als Kundendaten abgefragt oder dokumentiert.
4. Webhook-Verarbeitung und Abonnements für neue Nachrichten, Business-App-Echos
   und Synchronisierung an der konkreten Kundenverbindung nachweisen.
5. Kontoeignung, Eigentümerrechte, Mobilgerät, angebotene Importmöglichkeiten,
   Abrechnung und gegebenenfalls weitere Kontobedingungen konkret bestätigen.
6. Umfang, Datenschutzunterlagen, Zugangsschutz, Sicherung und Support für den
   Pilot festlegen. Keine rechtliche Freigabe aus diesem technischen Bericht.

Die Betriebsfreigabe bleibt unverändert. Es wurde kein Kunde angeschlossen,
keine Meta-Konfiguration geändert und keine Nachricht gesendet.

## Typische Unterbrechungen

| Situation | Vorgehen |
| --- | --- |
| Verbinden nicht eingerichtet | Betreiberkonfiguration vervollständigen; nicht die bestehende Nummer ersetzen |
| Fehlende Rechte / falsches Konto | Berechtigten Inhaber und richtige Assets prüfen; keine fremden Zugangsdaten anfordern |
| Abgelaufener oder unklarer Codeaustausch | Neuen Anschlussversuch starten; denselben Code nicht beliebig wiederverwenden |
| Kontoabonnement teilweise fehlgeschlagen | Vorhandene gezielte Fortsetzung nutzen; Status prüfen |
| Autorisiert, Automatik gesperrt | Synchronisierung und Abnahme abschließen; nicht als laufenden Assistenten verkaufen |
| Import fehlt / unvollständig | Umfang und Verzicht festhalten; Vollständigkeit nicht behaupten |
| Widerruf / erneuter Anschluss | Aktuelle Verbindungsversion prüfen; keine alten Antworten als aktuellen Erfolg anzeigen |

## Eingaben für die nächste Kostenanalyse C1

Für 1, 5 und 10 Werkstätten getrennt erfassen: einmalige begleitete Einrichtung
und Abnahme, laufender Support, Hosting/Datenbank/Sicherungen, AI-Verbrauch,
Meta-Nachrichten nach tatsächlicher Kategorie und Markt sowie Bildabrufe und
gegebenenfalls Partnergebühren. Mengenannahmen und gemessene Werte trennen.
Noch keine festen Minuten, Tarife, Preise oder Supportzusagen: Der reale erste
Anschluss liefert Messwerte für Einrichtung und Abnahme. Meta-Rechnungsträger
und Zahlungsweg gehören ausdrücklich in die Angebotsklärung.

## Quellen und Grenzen

Code und vorhandene M2-Berichte wurden gelesen; keine erneute vollständige
Testsuite, da ausschließlich Dokumentation ergänzt wird.
Die aktuellen öffentlichen Abrufe der folgenden Meta-Primärquellen lieferten
HTTP 429; ihre Inhalte wurden heute nicht erneut verifiziert:

- https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users
- https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers

Nächster konkreter Schritt: den aktuellen Meta-Anbieter-/Berechtigungsstand
lesend feststellen und die fehlenden Unternehmensunterlagen mit F1/F2 abgleichen.
Die Prozessbeschreibung für das Angebot liegt vor; der reale Anschluss bleibt offen.
