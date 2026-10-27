# M2, Aufgabe 2: Autorisiertes Embedded Signup

Stand: 27. Oktober 2026. **Die Anschlusskette ist lokal implementiert und mit
simuliertem Meta-HTTP geprüft. Keine reale Kundennummer, Meta-Zulassung oder
Coexistence-Betriebsfreigabe. Aufgabe 3 wurde nicht begonnen.**

## Korrekturen nach der unabhängigen Nachprüfung

Ausgangspunkt dieses Korrekturpakets ist `841db3f5e5ef02c9080a74a1b23b790a7d254629`.
Arbeitsbaum war sauber; `git ls-remote` bestätigte denselben Stand der bisherigen
Aufgabenbranch. Eigene Korrekturbranch: `codex/m2-signup-korrekturen-2026-10-27`.
Der unabhängige Prüfbericht und seine Python-/Browser-Reproduktionen wurden gelesen.

1. **Beide kontogebundenen Berechtigungen:** Neben der globalen Scope-Liste müssen
   `whatsapp_business_management` und `whatsapp_business_messaging` jeweils einen
   passenden Eintrag in `granular_scopes` haben. Ein vorhandener Eintrag ohne
   `target_ids` bedeutet gemäß der erneut gelesenen
   [Token-Dokumentation](https://developers.facebook.com/docs/graph-api/reference/debug_token/)
   uneingeschränkte Ziele; ein fehlender Eintrag bedeutet keinen Nachweis.
   Fremde, leere, nullwertige oder fehlerhaft typisierte Ziele und widersprüchliche
   doppelte Einträge werden vor Nummernabruf und Abonnement abgelehnt. Numerische
   ID-Strings und dokumentierte positive ganzzahlige IDs sind zulässig, Bool-Werte
   nicht. Regressionen prüfen beide Berechtigungen getrennt, einschließlich
   gemischter fehlerhafter Ziellisten. Die Erfolgsfixture weist jetzt beide nach.
2. **Versuchsgebundene Browser-Antworten:** Jede asynchrone Operation verwendet
   einen festen Laufbezug mit eigener Kennung. Vorbereitung, Popup-Start, Abbruch
   und Fortsetzung erzeugen jeweils einen neuen Bezug. Veraltete Antworten,
   Fehler, `finally`-Blöcke, SDK-Callbacks und Timer können den aktuellen Lauf
   nicht verändern. Statusantworten dürfen zusätzlich keine neuere Anzeige
   desselben Laufs überschreiben. Tests halten Antworten kontrolliert zurück,
   starten einen neuen Versuch und geben alte Erfolge bzw. Fehler erst danach
   frei. Der neue Versuch bleibt aktiv und wird genau einmal abgeschlossen.
3. **Gezielte CSP-Ergänzung:** Ausschließlich die Anschlussseite erlaubt jetzt
   `https://connect.facebook.net` auch in `connect-src`. Nonce, übrige Direktiven
   und andere Dashboard-Seiten bleiben geschützt. Ein Chrome-Test verwendet die
   tatsächlich gerenderte Seite samt tatsächlichem CSP-Header und die öffentlichen
   SDK-Dateien aus der unabhängigen Prüfung vom selben Tag. Alle Browser-Anfragen
   werden abgefangen: SDK-Dateien lokal ausgeliefert, App-Konfiguration und
   Startantwort synthetisch beantwortet, übrige Anfragen abgebrochen. Der echte
   `FB.init`-Abruf passiert die CSP. Gegenproben bestätigen die Sperre für Skripte
   ohne Nonce, fremde Verbindungsursprünge und SDK-Verbindungen anderer Seiten.
4. **Session-Schema ausdrücklich angefordert:** `extras.sessionInfoVersion` ist
   jetzt der String `"3"`, entsprechend der erneut gelesenen
   [Business-App-Anleitung](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users).
   Der Empfänger verlangt unverändert die numerische Payload-Version `3` und die
   exakten erlaubten Ursprünge. Signup v4 wird weiterhin durch die Login-Konfiguration
   gewählt. Die frühere Behauptung, der Parameter müsse fehlen, wurde korrigiert.
   Der Browser-Test weist auch nach, dass das echte SDK diesen Wert in den
   Parametern seiner abgefangenen OAuth-Popup-Anfrage weitergibt. Er belegt keinen
   erfolgreichen Meta-Login oder tatsächlichen Session-Callback.

Beide Primärquellen wurden vor der Korrektur erneut öffentlich gelesen: Web-Abruf
HTTP 429, anschließend direkter Dokumentationsabruf mit ausgewiesenem Client
jeweils HTTP 200. Keine Meta-Anmeldung und keine Graph-API-Nutzung mit Kundenzugang.

### Untersuchung des einmaligen Fehlers im vollständigen Prüflauf

Der unabhängige Lauf auf `841db3f` erfasste 583 Tests: 571 bestanden, elf wegen
fehlender PostgreSQL-Test-URL übersprungen, ein `KeyError: zustand`. Status und
Antwortinhalt der betroffenen Abschlussantwort fehlen im damaligen Protokoll.
Die Ursache kann deshalb nicht rückwirkend sicher bestimmt werden. Dessen
Gesamtdauer beträgt 33.221,594 Sekunden, also über neun Stunden; daraus folgt
allein weder ein Sitzungsablauf noch ein Ablauf des konkreten Anschlussversuchs.

Die Assertions des betroffenen Abbruch-/Ablauf-/Wiederverwendungstests prüfen nun
zuerst HTTP-Status und Antwortstruktur. Bei Abweichungen zeigen sie den begrenzten,
um synthetische Codes, Kennungen und Zugangswerte bereinigten Antwortinhalt.
Kein Retry und keine Unterdrückung. Eine zusätzliche kontrollierte Zeitgegenprobe
lässt erst während der simulierten Tokenprüfung 601 Sekunden verstreichen:
HTTP 409 mit lokalem Ablaufhinweis, kein Abonnement. Dies erklärt einen möglichen
Antworttyp ohne `zustand`, beweist aber nicht die Ursache des historischen Fehlers.

### Neue Prüfergebnisse des Korrekturpakets

- **585/585 Python-Tests im vollständigen Lauf bestanden**, keine übersprungenen
  Tests, Laufzeit 198,358 Sekunden. Darin **elf tatsächlich ausgeführte
  PostgreSQL-18-Tests**: sechs Anschluss-, vier Verbindungs- und ein allgemeiner
  Kommunikationstest. Eigene neu angelegte Wegwerf-Datenbank mit temporärem
  Dateisystem und synthetischen Zugangsdaten; Entfernen von Datenbankcontainer
  und Testnetz bestätigt. Die übrigen Tests verwenden überwiegend SQLite.
- **151/151 gezielte Python-Tests unter Windows/Python 3.14.3 bestanden**:
  Anschluss, Verbindungen, Fehlerdiagnose, Auth-Widerruf, HTTP-Sicherheit,
  WhatsApp-Zuverlässigkeit, Versand, Recovery und Abschlusszustände. Der frühere
  Abbruch-/Ablauftest bestand hier und im vollständigen Lauf ohne Wiederholung.
- **56/56 JavaScript-Tests bestanden**, davon 21 Anschlusstests. Vierzehn neue Fälle
  prüfen verspätete Erfolge/Fehler aller fünf Operationen, alte Timer/Callbacks,
  Status-Reihenfolgen und den fortgesetzt genau einmal abschließbaren neuen Versuch.
  Die abschließenden zwei Fälle sichern außerdem wiederholte Statusprüfungen beim
  Wiederherstellen und eine verspätete SDK-Initialisierung während der Fortsetzung.
- **Originale Zusatzreproduktionen bestanden:** ein Python-Gegentest zur fremden
  Messaging-Zuordnung sowie beide JavaScript-Gegenproben aus der Nachprüfung.
  Für die JS-Datei wurde lediglich der Quellpfad auf den aktuellen Arbeitsbaum
  angepasst; ihre Assertions blieben erhalten.
- **Browser-Prüfung mit echtem SDK und aktiver CSP bestanden**, einschließlich
  SDK-Konfigurationsabruf, Schemaweitergabe im abgefangenen OAuth-Popup und drei
  Sicherheitsgegenproben. Keine echte Anmeldung, kein erfolgreicher Meta-Callback.
- Kontrollierte Ablaufgegenprobe während HTTP: erwartete 409-Antwort und kein
  Kontoabonnement. Keine behauptete Aufklärung des historischen Einzelfehlers.

Ein erster gezielter Start enthielt versehentlich den nicht vorhandenen Modulnamen
`test_meta_fehlerdiagnose`: 44 Tests bestanden, ein Importfehler beim zusätzlichen
Modul. Korrigiert auf `test_whatsapp_fehlerdiagnose`; der anschließende 151er-Lauf
und der vollständige Lauf bestanden. Dieser Starterfehler wird nicht als grüner
Testlauf ausgegeben. Keine automatischen Wiederholungen fehlgeschlagener Tests.
Die Gruppen überschneiden sich und sind nicht zu einer Gesamtsumme zu addieren.
Echter Meta-HTTP-Transport war in Python gesperrt; die Prüfung nutzt den bestehenden
simulierten Transport. Diff- und Geheimnisprüfung ohne Befund.

### Lokaler Browser-Vertragsnachweis

`tests/whatsapp_sdk_csp_pruefen.cjs` benötigt die gepinnten Python-Testpakete,
Playwright, Chrome und zwei separat öffentlich geladene SDK-Dateien im ignorierten
Prüfordner: `meta-sdk-aktuell.js` von
`https://connect.facebook.net/de_DE/sdk.js` und `meta-sdk-bundle.js` von
`https://connect.facebook.net/de_DE/bundle/sdk.js/`. Die verwendeten öffentlichen
Kopien aus der unabhängigen Prüfung haben folgende SHA-256-Werte:

- SDK: `5f72c146ed1e98c3f73bf2e0e3bac1e303e602d8e7dd6a6741db2b582759b2ca`
- Bundle: `f0d80dff314a7f423177339063b44e7b549ffa4ef77878a8d6172cb38bce92ba`

Die lokalen Testpfade werden ausschließlich über `WERKSTATTAI_PRUEFSDK_ORDNER`,
`WERKSTATTAI_PRUEFPLAYWRIGHT`, `WERKSTATTAI_PRUEFCHROME` und optional
`WERKSTATTAI_PRUEFPYTHON` gesetzt. Keine neuen Anwendungsparameter oder Kundendaten.
Aufruf vom Projektverzeichnis: `node tests/whatsapp_sdk_csp_pruefen.cjs`.
Der Test startet selbst eine isolierte SQLite-Fixture, rendert die echten
Dashboard-Seiten und schließt Browser sowie Fixture anschließend wieder.
SDK-Kopien, Dokumentationsabrufe, Hilfsstarter und Protokolle verbleiben in
`artifacts/m2-signup-korrekturen/`, außerhalb von Git und Docker-Images.

## Ausgangspunkt und Wiederverwendung

Vor Beginn: sauberer Arbeitsbaum auf `codex/m2-korrekturen-2026-10-27`, Commit
`2569f573ddf107579fb729a44951b5639a4a0b7a`. `git fetch origin` bestätigte denselben
Remote-Stand. Die unabhängige Nachprüfung der beiden M2.1-Korrekturen einschließlich
der ursprünglichen Konkurrenz-Reproduktion wurde vom Auftraggeber bestätigt.
Die eigene Aufgabenbranch lautet `codex/m2-embedded-signup-2026-10-27`.
Kein Reset, Merge oder Rückgriff auf den unvollständigen historischen M1-/master-Stand.

Gelesen: `AGENTS.md`, Projektstand, Coexistence-Vorprüfung und M2.1-Bericht sowie
die tatsächlichen Verbindungs-, Auth-, Sicherheits-, Dashboard- und Versandwege.
Vorhanden waren bereits Nummernreservierung, atomare Versionswechsel, Fernet,
werkstattgebundener Resolver, Rollen und Sitzungsversionen, Kommunikationssperren,
dauerhafte Versandreservierung und bereinigte numerische Meta-Fehlerdiagnose.
Es fehlten Anschlussversuch, externer Verifikationsdienst, Dashboard-Flow und
die Automatik-Sperre für neue Coexistence-Verbindungen.

Diese Grundlage wird weiterverwendet. Es gibt keine zweite Tokenverwaltung,
keinen neuen Benutzerbestand und keine produktive Testbestätigungsroute.
Die bisherigen Entwurf-/Widerruf-Regressionen bleiben erhalten.

## Aktuell geprüfte Primärquellen und Protokoll

Die vier beauftragten Meta-Seiten wurden am 27. Oktober vor der API-Implementierung
aktuell gelesen. Der Web-Textabruf lieferte zunächst HTTP 429; der direkte öffentliche
Abruf mit ausgewiesenem Dokumentationsclient lieferte jeweils HTTP 200. Die
Dokumentationsinhalte wurden aus den eingebetteten CMS-Daten gelesen. Kein Login,
keine App-Konfiguration und kein Graph-API-Aufruf mit echten Zugangsdaten.

- [Embedded Signup v4](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/version-4):
  Die produktauswählende Login-for-Business-Konfiguration legt v4 fest. Kein
  ungeprüft übernommenes `extras.version = v3`. Die davon unabhängige
  Session-Schemaversion wird ausdrücklich mit `sessionInfoVersion: "3"` angefordert.
- [Business-App-Onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users):
  Für diesen Flow wird `featureType: whatsapp_business_app_onboarding` gesetzt.
  Nur `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` kommt als Abschluss infrage;
  dessen dokumentiertes Session-Payload hat weiterhin `version: 3` und kann nur
  eine `waba_id` enthalten. Die Session-Schemaversion ist nicht die Signup-Version.
  Die Nummer wird nicht registriert oder deregistriert; serverseitig müssen
  `is_on_biz_app = true` und `platform_type = CLOUD_API` bestätigt werden.
- [Implementierung](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation):
  SDK, Code-Callback und Session-Event sind getrennt. WerkstattAI akzeptiert
  ausschließlich die exakten Ursprünge `https://www.facebook.com` und
  `https://web.facebook.com`, keine Suffixprüfung und keine Konsolenprotokolle.
- [Tech-Provider-Onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-customers-as-a-tech-provider):
  Serverseitiger Codeaustausch über `GET /oauth/access_token`; Abonnement der App
  über `POST /{waba_id}/subscribed_apps`, anschließend lesend bestätigt.

Zusätzlich geprüft: [Token-Diagnose](https://developers.facebook.com/docs/graph-api/reference/debug_token/),
[Kontoabonnements](https://developers.facebook.com/documentation/business-messaging/whatsapp/reference/whatsapp-business-account/subscribed-apps-api)
und die [offizielle Meta-Sammlung zum Abruf der Kontonummern](https://www.postman.com/meta/whatsapp-business-platform/request/e9ady51/get-phone-numbers).
Der zunächst versuchte neue Dokumentationspfad für Kontonummern enthielt keinen
entsprechenden Artikel; er wird nicht als Nachweis verwendet. Der Adapter prüft
App-ID, Gültigkeit, Ablauf, beide WhatsApp-Berechtigungen und granulare Kontoauswahl.
Eine dokumentierte kontenübergreifende Berechtigung ohne `target_ids` ersetzt
nicht den anschließenden tatsächlichen Zugriff auf die Nummernliste des Kontos.

Die aktuelle Dokumentation nennt zusätzlich v5-Varianten. Hier wird ausdrücklich
der beauftragte v4-Ablauf über eine passende Login-Konfiguration verwendet.
Die Signup-Graph-Version ist separat auf den dokumentierten Standard v26.0 gesetzt;
die vorhandene M1-Versandkonfiguration bleibt unverändert.

## Implementierte Anschlusskette

`app/whatsapp_anschluss.py` verwaltet kurzlebige Versuche, `app/whatsapp_meta_anschluss.py`
den echten, im Test austauschbaren HTTP-Transport. Dashboard-Endpunkte liegen in
`app/whatsapp_anschluss_web.py`; der Einstieg „WhatsApp verbinden“ befindet sich
in den Einstellungen. Ohne erforderliche Konfiguration bzw. gültigen lokalen
Verschlüsselungsschlüssel bleibt die Funktion sichtbar als nicht eingerichtet.

1. Der Server prüft die bestehende Sitzung, Rolle `owner`/`admin`, Werkstatt und
   Demo-Sperre. Ein Inhaber kann ausschließlich seine eigene Werkstatt verbinden;
   ein Administrator benötigt ebenfalls einen expliziten Werkstattbezug.
2. Der Versuch erhält eine zufällige 256-Bit-Einmalkennung, zehn Minuten Laufzeit,
   erwartete Verbindungsversion und Bindung an Nutzer, Sitzung sowie den exakt
   konfigurierten HTTPS-Ursprung. Kennung und Sitzung werden nur als Hash gespeichert.
   Zustandsändernde Endpunkte verlangen zusätzlich den exakten Origin-Header und JSON.
3. Der Browser startet das SDK unmittelbar im Nutzerklick. Ereignisse werden auf
   Ursprung, Typ, Version, Abschlussart und numerische Asset-ID-Strings geprüft.
   Code und Asset-Ereignis können in beliebiger Reihenfolge eintreffen; erst beide
   lösen einmalig die serverseitige Prüfung aus. Abbruch, geschlossenes/blockiertes
   Popup, Ladefehler und fehlende Session-Antwort ergeben keinen lokalen Erfolg.
4. Vor dem ersten HTTP-Aufruf wird der Code als verbraucht beansprucht. Ein
   eindeutiger Code-Hash verhindert auch die Wiederverwendung in einem neuen Versuch.
   Der Code selbst wird nicht gespeichert. Das erhaltene Business-Token wird über
   Meta geprüft; die ausgewählte Nummer muss in der Kontonummernliste liegen.
   Fehlt die Browser-Nummer, wird nur eine eindeutig einzelne Kontonummer akzeptiert.
   Anzeigenummer und Coexistence-Merkmale stammen vom Serverabruf, nicht vom Browser.
5. Erst diese verifizierten Daten werden als unautorisierter Entwurf mit Herkunft
   `embedded_signup_coexistence` im bestehenden Verbindungsmodell gespeichert.
   Die App wird am richtigen Kundenkonto abonniert. Ein lesender Abruf muss die
   eigene App-ID unter `whatsapp_business_api_data` nachweisen.
6. Der dauerhafte Abschluss prüft Sitzung, Rolle, Werkstatt, Ablauf, Versuchszustand,
   Version und Übereinstimmung des gespeicherten Entwurfs nochmals. Ein weiterer
   atomarer Versionswechsel erzeugt ein passendes neues Fernet-Chiffrat. Erst dann
   werden Autorisierung und Verbindungszustand bestätigt. `coexistence_bereit` bleibt 0.

Lokale Transaktionen sperren Nutzer und Kommunikationsbereich vor Werkstatt und
Versuch. Die Versuchzeile wird auf PostgreSQL ebenfalls mit `FOR UPDATE` gesperrt:
Logout und dauerhafter Abschluss werden dadurch atomar geordnet, auch wenn der
Abschluss den Versuchszustand bereits gelesen hat. HTTP liegt vollständig
außerhalb dieser Sperren. Die bestehende
Versionsbedingung beim tatsächlichen Verbindungsschreiben und die Zeilenzahlprüfung
verhindern, dass ein verspäteter Abschluss Widerruf oder Neuanschluss überschreibt.
Der Abbruch eines Versuchs kann einen bereits begonnenen externen Schritt nicht
rückwirkend ungeschehen machen; er verhindert dessen spätere lokale Bestätigung.

## Dauerhafte Fehler- und Wiederaufnahmezustände

| Zustand | Bedeutung und erlaubte Fortsetzung |
| --- | --- |
| `offen` | Einmaliger Codeabschluss innerhalb der Laufzeit zulässig. |
| `austausch` | Code bereits beansprucht; kein zweiter Austausch. Nach Prozessabbruch neuer Versuch. |
| `abonnement` | Verifizierter Zugang verschlüsselt gespeichert; externe Bestätigung läuft. |
| `teilfehler` | Kontoabonnement unbestätigt. Explizites Fortsetzen prüft Token/Assets erneut, liest zuerst den Abonnementzustand und abonniert nur bei fehlendem Nachweis erneut. |
| `unklar` / `fehlgeschlagen` | Kein bestätigter Anschluss; frischer Meta-Versuch erforderlich. |
| `abgebrochen` / `abgelaufen` | Keine weitere Bestätigung zulässig. Logout beendet aktive Versuche dieser Sitzung. |
| `abgeschlossen` | Zugang bestätigt, Automatik weiterhin gesperrt. |
| `ueberholt` | Statusanzeige eines Abschlusses, dessen Verbindung inzwischen geändert/widerrufen wurde. |

Ein neuer Versuch ersetzt ältere aktive Versuche derselben Werkstatt. Nach
Nummernkonflikt wird die lokale Reservierung zurückgerollt. Externe Ablehnungen
enthalten ausschließlich HTTP-Status sowie streng typisierte numerische Codes/
Subcodes. Keine Providertexte, Codes, Token, Header oder Rohantworten in UI,
Versuchsdiagnose oder Anwendungslogs. Paging-URLs und Weiterleitungen werden
nicht mit Kundenzugängen verfolgt. Es gibt Größen- und Zeitgrenzen für HTTP.

## Serverseitige Automatik-Sperre

Die Sperre gilt vor normaler Eingangsspeicherung, Kundenaktivität, Ticket-/Intake-
Verarbeitung, Wiederaufnahme vorbereiteter Antworten und unmittelbar vor deren
HTTP-Versand. Auch ein anderer alter, unklarer Versand löst für gesperrte
Coexistence keine dauerhafte automatische Wiederholung aus.

Nicht freigegebene Eingänge werden in `whatsapp_zurueckgehalten` einmalig über
Werkstatt und Nachrichtenkennung mit Nummern-ID, Zeit und Sperrgrund erfasst.
Keine Nachrichtentexte, Kundenrufnummern oder Medien werden dabei importiert.
Der signierte Webhook wird erfolgreich quittiert. Es entstehen keine normalen
Eingangsnachrichten und kein neues 24-Stunden-Fenster. Wiederholte zurückgehaltene
Kennungen bleiben auch nach einer späteren Freigabe ausgeschlossen; es gibt keine
automatische Nachverarbeitung. Das Dashboard zeigt Anzahl und letzten Zeitpunkt.

Der Resolver bleibt für ausdrücklich manuellen Zugang verwendbar. Insbesondere
ist ein bestätigter Zugang keine Automatik-Freigabe; die Bereitschaftsanzeige
bleibt für Coexistence unvollständig. Das Zeitfenster bleibt während der Sperre
geschlossen. Die begrenzte eigene M1-Legacy-Verbindung behält ihr bisheriges
Verhalten. Herkunftsschutz verhindert, dass ein späterer interner Entwurf eine
bestehende Coexistence-Sperre durch Umbenennen der Herkunft verliert.

Echoauswertung, Kontolebenszyklus und Historien-/Kontaktsynchronisierung werden
hier nicht implementiert. Bereits vor einer lokalen Sperre begonnene externe
HTTP-Aufrufe können nicht nachträglich zurückgerufen werden.

## Konfiguration und noch ausstehende Meta-Schritte

Neue Umgebungsvariablen, ohne reale Werte:

- `WHATSAPP_APP_ID`
- `WHATSAPP_SIGNUP_CONFIG_ID`
- `WHATSAPP_SIGNUP_ORIGIN`
- `WHATSAPP_SIGNUP_GRAPH_VERSION` (optional; Standard v26.0)

Wiederverwendete Servervoraussetzungen: `WHATSAPP_APP_SECRET`,
`WHATSAPP_ZUGANGSSCHLUESSEL`, `AUTH_SECRET`; für Webhook-Einrichtung zusätzlich
`WHATSAPP_VERIFY_TOKEN` und `WHATSAPP_WEBHOOK_PUBLIC_URL`. Der globale
`WHATSAPP_ACCESS_TOKEN` ist kein Ersatz für Kundenzugänge.

Vor einem echten Anschluss fehlen weiterhin die bereits dokumentierten
Tech-Provider-/Unternehmens- und App-Review-Freigaben für die verwendeten Produkte
und WhatsApp-Berechtigungen. Im Meta-Dashboard muss eine passende v4-Konfiguration
mit Business-App-Onboarding, korrekter App-ID, HTTPS-Domain, JavaScript-SDK-Login
und gültigen OAuth-Weiterleitungsadressen eingerichtet sein. Die tatsächliche
Konfiguration und Eignung einer Kundennummer wurden nicht geprüft oder verändert.
App-weite Webhook-Felder werden hier nicht eingerichtet; das Kundenkontoabonnement
allein implementiert noch keinen Echo-/Historienverbraucher. Die Synchronisierung
und ihre von Meta geforderten Fristen müssen vor einem realen Anschluss gelöst sein.

Keine Bedingungen angenommen, Rechte vergeben, Nummer registriert, Nachricht
versendet, Produktion verändert oder Deployment ausgelöst.

## Historische Prüfungen der Erstimplementierung

- Zuerst gezielte SQLite-Läufe unter Windows/Python 3.14.3: zunächst 22 bestehende
  Verbindungs-/Fehlerdiagnosetests und 20 neue Anschlusstests; nach Ergänzungen
  46 Tests (24 Anschluss + 17 Verbindung + 5 Fehlerdiagnose), alle bestanden.
- Danach 9/9 gezielte PostgreSQL-18-Tests unter Python 3.12.13: fünf neue
  Anschlussfälle und vier erhaltene Verbindungs-/Konkurrenztests. Nach Ergänzung
  des Code-Hash-Schutzes erneut 9/9 bestanden.
- **581/581 Python-Tests im vollständigen Regressionslauf bestanden**, keine
  übersprungenen Tests. Darin zehn tatsächlich ausgeführte PostgreSQL-Tests
  (fünf Anschluss, vier Verbindung, ein bestehender Kommunikationstest).
  Die übrigen Tests verwenden überwiegend temporäres SQLite; kein vollständiger
  PostgreSQL-Anwendungs- oder Lasttest.
- Nach den letzten Ergänzungen zu Schlüsselkonfiguration und Unterdrückung
  wartender Antworten: **100/100 gezielte Anschluss-/Versand-/Recovery-Tests**
  unter Windows/Python 3.14.3 bestanden. Die abschließende Bereitschaftsanzeige
  wurde separat mit **42/42 Anschluss-/Verbindungstests** geprüft (25 + 17).
- Abschließend **10/10 gezielte PostgreSQL-18-Tests** bestanden (sechs Anschluss,
  vier Verbindung). Der zusätzliche deterministische Konkurrenztest hält den
  Abschluss nach dem Lesen der Versuchzeile an und weist nach, dass ein paralleler
  Logout bis zum Transaktionsende wartet. Die andere Reihenfolge, Logout während
  HTTP vor dem Abschluss, bleibt ebenfalls abgedeckt. Dieser letzte Lauf prüft
  die ergänzte Zeilensperre; er ist kein erneuter vollständiger Regressionslauf.
- **42/42 JavaScript-Tests bestanden**, einschließlich sieben neuer Tests für
  exakte Ursprünge, Schema, Abbruch, Callback-Reihenfolge, einmaligen Abschluss,
  SDK-Fehler und Zeitgrenzen. Kein echter SDK-/Popup-Durchlauf mit Meta.

Die Läufe überschneiden sich; alte M2.1-Nachweise werden nicht als neue Tests
ausgegeben. Der Meta-Adapter wurde über simuliertes HTTP geprüft, nicht über
einen privilegierten Testendpunkt. Tests bestätigen unter anderem: fremde
WABA/Nummer, fehlende Rechte, Tokenablauf, Logout/Rollenverlust während HTTP,
gleichzeitige Abschlüsse, späteren Widerruf, Nummernkonflikt, Timeouts vor/nach
Tokenaustausch und Abonnement, Geheimnisbereinigung, signierte wiederholte Text-/
Bild-/historische Eingänge ohne Automatik und erhaltenes Legacy-Verhalten.

Alle Daten und Zugangswerte sind synthetisch. PostgreSQL lief in neu angelegten
Containern mit temporärem Dateisystem, zufälligem Testpasswort und eigenem Netz.
Nur ausgewählte Quell-/Testverzeichnisse wurden lesbar eingebunden, keine `.env`
oder lokalen Daten. Echter HTTP-Transport war in den Tests blockiert. Entfernen
der Datenbanken und Testnetze wurde bestätigt. Lokale Dokumentationskopien,
Prüfskripte und Protokolle bleiben ausschließlich im ignorierten und vom
Docker-Image ausgeschlossenen `artifacts/m2-signup/`.

## Lokale Testanleitung

Aus dem Projektverzeichnis mit den gepinnten Paketen aus `requirements-test.txt`
und leerem `DATABASE_URL`:

```powershell
$env:APP_ENV = 'test'
$env:DATABASE_URL = ''
python -m unittest discover -s tests -p test_whatsapp_anschluss.py
node --test tests/test_whatsapp_anschluss.mjs
```

Die Tests legen ihre eigenen SQLite-Dateien an und ersetzen den HTTP-Transport.
Sie benötigen weder echte Tokens noch eine Meta-App. Für PostgreSQL zuerst eine
**separate leere Wegwerf-Datenbank** starten, deren URL ausschließlich über
`WERKSTATTAI_TEST_POSTGRES_URL` setzen, und dann:

```powershell
python -m unittest discover -s tests -p test_whatsapp_anschluss_postgres.py
python -m unittest discover -s tests -p test_whatsapp_verbindungen_postgres.py
```

Ohne diese Test-URL werden PostgreSQL-Tests ausdrücklich übersprungen und gelten
nicht als geprüft. Keinesfalls eine Produktions- oder bestehende Kundendatenbank
verwenden. Der dokumentierte Lauf nutzte Python 3.12.13 im Container, da die
gepinnten PostgreSQL-Pakete nicht zur lokalen Windows/Python-3.14-Laufzeit passen.

## Grenze und genau ein nächster Schritt

Fertig ist die lokal implementierte, simuliert geprüfte Anschlusskette. Reale
Meta-Zulassung, tatsächlicher Browser-/SDK-Durchlauf und Kundenanschluss sind
**nicht geprüft**. Die vollständige Coexistence-Freigabe bleibt ausgeschlossen.

**Nächster Schritt:** Unabhängige Nachprüfung der Korrekturen von Aufgabe 2.
