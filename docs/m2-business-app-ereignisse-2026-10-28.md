# M2, Aufgabe 3: Business-App-Ereignisse und Kontolebenszyklus

Stand: 28. Oktober 2026. Lokale Implementierung mit synthetischen Verbindungen,
signierten Webhooks und simuliertem Transport. Keine reale Meta- oder
Coexistence-Betriebsfreigabe.

## Korrekturen nach der unabhängigen Nachprüfung vom 28. Oktober 2026

Ausgangspunkt dieser Korrekturen ist `123f807ce0c8a5d1905f9c9d949576296c6fd2cd`,
lokal und remote identisch bei sauberem Arbeitsbaum. Eigene Branch:
`codex/m2-business-app-korrekturen-2026-10-28`. Gelesen wurden der unabhängige
`PRUEFBERICHT.txt`, `gegenproben.py` und beide Gegenproben-Protokolle unter
`C:\Users\Mikolaj\Documents\New project\m2-business-app-review-2026-10-28`.
Die dort bestätigten 618 Python- und 58 JavaScript-Tests sind historische
Nachweise; die zwei zusätzlichen Gegenproben zeigten trotzdem reale Lücken.

### 1. Verspätete erste Zustellung nach bewusstem Fortsetzen

**Ursache:** Die Verbindungsversion und `verbunden_seit` unterscheiden keine
manuellen Entscheidungen innerhalb einer Verbindung. Eine erstmals gelieferte
ältere Provider-ID konnte deshalb eine spätere Assistentenfreigabe überschreiben.

**Korrektur:** Die vorhandene Gesprächskontrolle speichert zusätzlich
`assistent_freigegeben_am`, ausschließlich bei einer ausdrücklichen Freigabe.
Der Zeitpunkt wird mit Moduswechsel und Echo-Quittierung in derselben Transaktion
unter derselben Kommunikationssperre festgehalten, getrennt je Werkstatt und
Kundengespräch. Er läuft bei zurückgestellter Systemuhr nicht rückwärts.
Sowohl die Freigabe im Posteingang als auch diejenige am verknüpften Ticket
werden berücksichtigt. Automatische Wiederherstellung nach Versandfehlern,
Ticketnotizen und sonstige Statusänderungen setzen keinen Freigabezeitpunkt.

Neue Echo-Datensätze behalten ihren Providerzeitpunkt. Liegt dessen Sekunde
eindeutig vor der Freigabesekunde, bleibt das Echo sichtbar und dauerhaft als
`echo_veraltet` quittiert: keine neue Übernahme, Kontrollrevision oder Ticketnotiz.
Eine eindeutig spätere Telefonantwort darf weiterhin übernehmen, sofern auch
ihre Herkunft geklärt ist. Die Prüfung erfolgt sowohl beim Empfang als auch
unmittelbar vor einer späteren fachlichen Übernahme nach Versandklärung.

**Grenze:** In derselben Sekunde oder bei fehlendem gespeicherten Zeitnachweis
ist die Reihenfolge nicht belegt. Dann bleibt `echo_pruefung` ohne Zustandswechsel
bestehen und sperrt weitere automatische Antworten. Bewusstes Fortsetzen nach
Verlaufsprüfung quittiert auch diesen Fall dauerhaft. Ein beliebiges `updated_at`
wird nicht als manuelle Freigabe ausgegeben. Die additive Migration lässt den
neuen Zeitpunkt für Altbestände leer; frühere, nicht protokollierte Freigaben
lassen sich daraus nicht rekonstruieren. Die zeitliche Einordnung setzt
vergleichbare korrekte System-/Providerzeiten voraus, keine globale Reihenfolge.

### 2. Erfolgsbestätigung ohne Provider-ID

**Ursache:** Das Ende einer `sending`-Reservierung wurde mit ausgeschlossener
API-Zuordnung verwechselt. Recovery `sent` ohne Provider-ID belegt lediglich den
Versandstatus, nicht die fremde Herkunft eines Echos.

**Korrektur:** Ein erfolgreicher oder weiterhin unklarer Kandidat ohne Provider-ID
bleibt für die Echo-Zuordnung relevant, auch wenn Recovery seine Reservierung
beendet hat oder das Echo erstmals danach eintrifft. Fehlende Kandidatendaten
liefern ebenfalls keinen Ausschlussbeweis. Erst eine abweichende bekannte
Provider-ID oder eine eindeutige negative Versandklärung schließt den Kandidaten
aus. Bei weiterhin möglicher Zuordnung entstehen keine zusätzliche Übernahme
und keine Ticketnotiz; der Prüfzustand bleibt erhalten.

Die gemeinsame Versandfinalisierung darf eine verspätet belegte Provider-ID
auch nach manueller Erfolgsbestätigung ergänzen, wenn sie zum selben reservierten
Transportversuch gehört. Identische Provider-ID führt das Echo in die ursprüngliche
Sendung zusammen, auch nach vorheriger ausdrücklicher Quittierung. Die manuelle
Statusentscheidung, Fragen und Kontrollzustände werden dabei nicht nochmals
ausgeführt. Ein anderer Transportbeginn darf keine Identität nachtragen. Text
und Zeitähnlichkeit sind weiterhin kein Identitätsnachweis.

**Grenze:** Ohne Identitätsnachweis bleibt die Zuordnung offen. Nach Prüfung kann
die Werkstatt weiterhin bewusst fortsetzen; erneute Echozustellung hebt diese
Quittierung nicht auf. Noch laufendes `sending/unknown` muss zuvor über den
bestehenden Recovery-Weg geklärt werden. Kein automatischer Neuversand, keine
pauschale Aufhebung anderer Reservierungen. Falsche manuelle Bestätigungen können
lokal nicht durch Wissen über den tatsächlichen Meta-Transport ersetzt werden.

### Übernommene und ergänzte Regressionen

Beide unabhängigen Methoden stehen mit unveränderten Methodenrümpfen und
fachlichen Assertions in `tests/test_whatsapp_echo_korrekturen.py`; ein lokaler
AST-Vergleich bestätigt die Übereinstimmung. Nur Modul-/Fixture-Einbindung und
Testklassen wurden angepasst, damit die bestehenden Tests nicht zusätzlich
geerbt und doppelt gezählt werden. Dieselben Fälle laufen auf SQLite und PostgreSQL.

Zusätzliche Nachweise prüfen neue/alte Antworten, gleiche Sekunde, parallele
Zustellung, angehaltene Freigabetransaktion, neue Provider-ID in einem separaten
Python-Prozess, Ticketfreigabe, automatische Fehlversand-Wiederherstellung,
Recovery mit/ohne spätere Provider-Zuordnung, unveränderte Ticketnotizen,
bewusste Quittierung und Isolation zweier Werkstätten. Events und Barrieren
ordnen die Konkurrenzfälle; keine zufälligen Sleeps oder automatischen Test-Retries.

Eine bestehende Ticket-Fixture kennzeichnet ihre reine Anfangszuordnung nun als
`ausdrueckliche_freigabe=False`; ihre fachlichen Assertions bleiben unverändert.
Die Vorläufe zeigten außerdem eine ungeeignete Freitextsendung in der neuen
Fehlversand-Fixture. Ein zunächst ergänzter Eingangszeitpunkt reichte nicht:
`coexistence_bereit=0` sperrt das Fenster weiterhin absichtlich. Die Fixture nutzt
nun eine simuliert abgelehnte Vorlagensendung, um ohne Bereitschaftsfreigabe die
eigentlich zu prüfende automatische Wiederherstellung zu erreichen.

### Neue Prüfnachweise dieser Korrektur

- **650/650 Python-Tests** mit Python **3.12.13** in **246,825 Sekunden**
  bestanden, keine Auslassungen. Darin **35 PostgreSQL-Tests** auf einer frisch
  angelegten leeren Wegwerfdatenbank mit PostgreSQL **18.6** und psycopg **3.2.3**;
  SQLite-Version **3.46.1**. Beide unveränderten Gegenproben sowie alle ergänzten
  Korrekturfälle liefen auf beiden Datenbanken. Prüfcontainer und isoliertes
  Prüfnetz wurden anschließend entfernt; der Bereinigungsnachweis bestätigt dies.
- **126/126 gezielte Python-Regressionen** mit Python **3.14.3** bestanden:
  Korrektur-/Gegenproben auf SQLite, Recovery, Versandfinalisierung,
  Kommunikationsmodell, Auth-Widerruf und Anschluss.
- **58/58 JavaScript-Tests** mit Node.js **24.16.0** bestanden, keine Auslassungen.
- Beide übernommenen Gegenproben wurden per AST-Vergleich auf unveränderte
  Methodenrümpfe geprüft. Lokaler Nachweis: `gegenproben_vergleich.json`.

Die Gruppen überlappen und werden nicht addiert. Neue lokale Protokolle und
Prüfstarter liegen ausschließlich unter `artifacts/m2-business-app-korrekturen/`;
dieses Verzeichnis bleibt von Git und Docker-Images ausgeschlossen. Echtes Meta
ist nicht geprüft. `coexistence_bereit=0` und die bestehenden Automatik-Sperren
bleiben unverändert; Aufgabe 4 wurde nicht begonnen.

Die folgenden Abschnitte dokumentieren die **historische Erstimplementierung**.
Ihre Testergebnisse sind keine neuen Ergebnisse dieser Korrektur.

## Ausgangspunkt und wiederverwendete Funktionen

Ausgangspunkt war `533c7aeb41db9e7acf07a3bc50615d4fc8c77305`, lokal und auf dem
Remote identisch, mit sauberem Arbeitsbaum. Eigene Aufgabenbranch:
`codex/m2-business-app-ereignisse-2026-10-28`.

Aufgaben 1 und 2 einschließlich des späten Abbruchs sind unabhängig lokal
abgenommen. Gelesener Nachweis:
`C:\Users\Mikolaj\Documents\New project\m2-signup-abbruch-review-2026-10-28\PRUEFBERICHT.txt`.
Die dortigen 591 Python- und 58 JavaScript-Tests sind historische Ergebnisse.
Die bisherigen Berichte bleiben erhalten.

Wiederverwendet werden `whatsapp_verbindungen`, dessen verschlüsselte Zugänge
und Versions-CAS, `atomic_database`, die Kommunikationssperre, Kontrollrevisionen,
Ticketnotizen, `whatsapp_messages`, `whatsapp_events`, Versandfinalisierung und
Recovery sowie der bestehende mandantengebundene Bildabruf. Es gibt keine zweite
Tokenverwaltung, Nachrichtenablage oder produktive synthetische Verbindung.

## Am 28. Oktober 2026 gelesene Primärquellen

Der erste Textabruf der [Coexistence-Onboarding-Dokumentation](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users)
lieferte HTTP 429. Ein öffentlicher HTML-Leseabruf ohne Anmeldung lieferte HTTP
200. Der eingebettete CMS-Artikel wurde lokal extrahiert und gelesen; ebenso
die darin verlinkte [account_update-Referenz](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/account_update).
Dokumentationskopien liegen ausschließlich im ignorierten Prüfverzeichnis.

Belegte Felder und ihre Verwendung:

| Feld/Ereignis | Belegter Bezug und lokale Entscheidung |
| --- | --- |
| `messages` | Nur dieses `change.field` darf `value.messages` und `value.statuses` in die bisherigen Pfade geben. |
| `smb_message_echoes` | `value.message_echoes`; `to` ist der Kunde, `from` die Geschäftsnummer; `entry.id` und `metadata.phone_number_id` bestimmen gemeinsam die Verbindung. |
| `account_update / PARTNER_REMOVED` | Trennung in der Business-App oder Entzug der Partnerschaft. Optional `phone_number` begrenzt die Reichweite auf eine eindeutig zugeordnete Anzeigenummer. |
| `account_update / PARTNER_APP_UNINSTALLED` | App deautorisiert/deinstalliert. `waba_info.partner_app_id` muss unserer konfigurierten App entsprechen. |
| `account_update / ACCOUNT_OFFBOARDED` | Dokumentiertes Offboarding, etwa bei Gerätewechsel/Neuregistrierung; ohne Nummernbezug werden alle autorisierten Verbindungen dieser WABA gesperrt. |
| `account_update / ACCOUNT_DELETED` | Gelöschtes Konto: Zugang sperren, lokale Nachrichten und Tickets erhalten. |
| `ACCOUNT_RECONNECTED` und andere Ereignisse | Keine automatische Autorisierung, Wiederaufnahme oder Freigabe. |
| `history`, `smb_app_state_sync` | Reserviert, ohne Kundenannahme, Kontakt- oder Historienimport. |

Bei den dokumentierten Partner-Payloads kann `entry.id` das Partnerunternehmen
bezeichnen; das betroffene Kundenkonto steht dann in `waba_info.waba_id`.
Es wird deshalb nicht mit einer erfundenen WABA ersetzt oder fälschlich zwingend
mit `entry.id` gleichgesetzt. Ohne `waba_info` verwendet die dokumentierte
Business-App-Variante die Konto-ID aus `entry.id`. Die Herkunft wird zuerst über
die bestehende HMAC-Prüfung, danach über die gespeicherte Konto-/Nummernbindung
geprüft. `disconnection_info` enthält Diagnosegründe, keinen zusätzlichen
Ereignistyp und keine Autorisierung; Rohtexte daraus werden nicht gespeichert.

Für eine spätere Kontofreigabe müssen die tatsächlich verwendeten Abonnements
`messages`, `smb_message_echoes`, `account_update` sowie für Aufgabe 4 `history`
und `smb_app_state_sync` überprüft werden. In diesem Auftrag wurde kein echtes
Meta-Abonnement geändert. Signup-Version und Session-Schema bleiben unverändert.

## Verarbeitung und dauerhafte Entscheidungen

Der Dispatcher validiert die gesamte Lieferung vor fachlichen Seiteneffekten.
Fehlende, unbekannte oder falsch typisierte Felder fallen nicht in den normalen
Eingangspfad. HMAC, Body-Grenzen und die Grenze von 100 Ereignissen bleiben
erhalten; Texte/Bildunterschriften sind auf 4096 Zeichen begrenzt. Kontosperren
werden innerhalb gemischter Pakete vor neuen Eingängen verarbeitet. Alte
Test-Payloads wurden an Feld-, Objekt- und WABA-Zuordnung angepasst; der Parser
wurde dafür nicht permissiver gemacht. Der begrenzte M1-Legacy-Pfad bleibt.

Ein neues, eindeutig externes Echo wird unter der Kommunikationssperre einmalig
als ausgehende Werkstattnachricht gespeichert. Quelle: `whatsapp_business_app`;
Provider-ID und Verbindungsversion bleiben erhalten. Das ausdrücklich verknüpfte
aktive Ticket erhält eine `workshop_notification`. Ohne eindeutige Verknüpfung
wird kein Ticket erzeugt. Die Unterhaltung wechselt transaktional zur Werkstatt;
offene Fragen und Reparaturstatus werden nicht aufgelöst oder verändert. Das
Echo eröffnet kein Kundenservice-Fenster und löst keinen API-Versand aus.

Die bestehende Provider-ID-Eindeutigkeit und der persistierte Verarbeitungszustand
verhindern erneute Übernahme nach bewusstem Fortsetzen, bei Parallelzustellung
und nach Prozessneustart. Gleicher Text oder ähnliche Uhrzeit reichen ausdrücklich
nicht zur Zuordnung zu einer eigenen API-Sendung.

Ist die Provider-ID bereits bekannt, wird die bestehende Sendung bestätigt.
Trifft ein Echo vor der HTTP-Antwort bei noch unbekannter Provider-ID ein, hält
derselbe Nachrichtenbestand es mit `echo_pruefung` und den damaligen
Versandkandidaten fest. Es erzeugt zunächst keine Ticketnotiz oder zweite
Werkstattübernahme; weitere automatische Antworten sind gesperrt. Die gemeinsame
Finalisierung führt ein passendes Echo anhand der tatsächlichen Provider-ID in
die ursprüngliche Sendung zusammen. Andere Echos werden erst nach eindeutiger
Klärung der betreffenden Versandkandidaten als externe Nachrichten übernommen.
Ein Timeout bleibt `sending/unknown`; er ist keine Erlaubnis zur Wiederholung.
Frühe Zustellstatus werden im vorhandenen Ereignisjournal mit eindeutiger Kennung
gesichert und nach der Provider-Zuordnung monoton angewendet. Providerfehler
übernehmen ausschließlich numerische Codes, keine Rohantworten oder Fehlertexte.

Vorbereitete Antworten prüfen die Kontrollrevision bei Reservierung und erneut
am letzten lokalen Übergabepunkt vor dem Transport. Ein offenes Echo sperrt auch
diesen Übergang. Die Finalisierung hebt keine fremden Reservierungen auf.
Bereits gestartete externe Aufrufe lassen sich nicht zurückrufen; die lokale
Prüfung und der Beginn eines externen HTTP-Aufrufs sind keine verteilte atomare
Operation. Es wird keine globale Exactly-once-Garantie behauptet.

## Kontoereignisse, Neuanschluss und Zeitgrenzen

Für neue Verbindungsversionen wird `verbunden_seit` gespeichert; bestehende
Datensätze erhalten bei der Migration ihren vorhandenen Änderungszeitpunkt.
Kontomeldungen vergleichen WABA, gegebenenfalls Anzeigenummer, Providerzeit und
die vor der Verarbeitung gelesene Verbindungsversion. Die eigentliche Sperre
verwendet `widerrufe_verbindung` mit Versions-CAS. Ein kontoweites Ereignis
behandelt alle tatsächlich zugeordneten Nummern dieser WABA; andere Konten
bleiben unverändert. Eindeutige Ereignisschlüssel liegen im vorhandenen Journal.

Meta liefert nur sekundengenaue Ereigniszeiten und keinen lokalen
Verbindungs-Versionsbezug. Bei derselben Sekunde wie der Neuanschluss wäre eine
sichere Reihenfolge unbelegt. Ein solches Kontoereignis überschreibt die neue
Verbindung deshalb nicht, sperrt aber versionsgebunden die Zugangsnutzung bis
zu einem erneut verifizierten Anschluss. Der vorhandene Resolver sperrt damit
Versand und Medien; auch die Automatik bleibt gesperrt. Deutlich ältere
Ereignisse und bereits entschiedene Wiederholungen werden ignoriert.

Ein zeitlich ebenso unzuordenbares Echo bleibt sichtbar und hält die Automatik
an. Nach Prüfung des Verlaufs kann die Werkstatt ausdrücklich fortsetzen;
laufende oder unklare Sendungen müssen weiterhin zuerst über Recovery geklärt
werden. Die Quittierung bleibt dauerhaft und erzeugt keine spätere Übernahme.

Diese Grenzen hängen von korrekten Providerzeiten ab. Ohne Provider-Generation
kann lokale Software keine vollständige globale Reihenfolge beweisen. Eine
spätere reale Meta-Erprobung muss insbesondere die tatsächlichen Payloads,
Abonnements, Verzögerungen und den betrieblichen Umgang mit Prüfzuständen prüfen.

## Oberfläche, Medien und Betriebsgrenzen

Texte und vorhandene Metadaten für Bild, Audio, Video, Dokument und Sticker
bleiben im bestehenden Nachrichtenverlauf. Bilder verwenden den geschützten
Medien-Endpunkt; fremde Werkstätten erhalten keinen Zugriff. Die Oberfläche
zeigt ausgehende Werkstattnachrichten und erklärt eine offene Echo-Zuordnung.
Es gibt keine OCR, Sprachauswertung oder automatische Reparaturfreigabe.

Neue Coexistence-Verbindungen bleiben `coexistence_bereit=0`. Normale
Coexistence-Eingänge bleiben dauerhaft von automatischer Nachverarbeitung
ausgeschlossen. Echo und Kontolebenszyklus arbeiten unabhängig von dieser
Bereitschaftssperre. Aufgabe 4 wurde nicht begonnen. Keine echten Nachrichten,
Kundenanschlüsse, Kontokonfigurationen, Produktionsänderungen oder Deployments.

## Tatsächlich ausgeführte Prüfungen

Am 28. Oktober 2026 auf dem abschließenden Implementierungsstand:

- **618/618 Python-Tests bestanden**, keine Auslassungen, Laufzeit 225,599 Sekunden.
  Python **3.12.13**, SQLite **3.46.1**, PostgreSQL **18**, gepinnter Treiber
  `psycopg[binary]==3.2.3`. Die vollständige Suite enthält Anschluss-, Auth-,
  Reliability-, Dispatch-, Recovery-, Kommunikations-, Medien- und
  Datenschutzregressionen sowie die unveränderte späte-Abbruch-Gegenprobe.
- Darin **19 tatsächlich ausgeführte PostgreSQL-Tests**: die bisherigen 14 und
  fünf neue Ereignisfälle. Eine eigens angelegte leere Datenbank mit zufälligem
  Prüfzugang und eigenem Netz wurde verwendet. Beide wurden anschließend
  nachweislich entfernt. Keine bestehende Kunden- oder Produktionsdatenbank.
- Neu sind **22 SQLite-Ereignistests** und die fünf PostgreSQL-Fälle. Die
  Konkurrenzfälle verwenden Events/Barrieren: parallele Echos, Vorbereitung
  gegen Übernahme, Übernahme während der Reservierung, Wiederholung nach
  bewusstem Fortsetzen sowie Widerruf gegen neue Verbindungsversion. Zusätzlich
  werden frühes eigenes Echo und Zustellstatus auf PostgreSQL geprüft.
- Ein weiterer Test startet einen **neuen Python-Prozess** gegen die isolierte
  SQLite-Datei und bestätigt die unveränderte Entscheidung nach Fortsetzen.
- **58/58 JavaScript-Tests bestanden**, Node.js **24.16.0**, keine Auslassungen.
- Zuvor **66/66 gezielte Python-Regressionen** auf Python **3.14.3** bestanden.
  Diese Gruppe überlappt die vollständige Suite und wird nicht hinzuaddiert.
- Diff-/Whitespace- und Geheimnisprüfung ohne Befund. Dokumentationskopien,
  Protokolle und Prüfstarter bleiben unter `artifacts/m2-business-app/`, außerhalb
  von Git und Docker-Images; `.gitignore` und `.dockerignore` schließen sie aus.

Die konkurrierenden signierten SQLite-Aufrufe für paralleles Echo und Vorbereitung
rufen den echten HMAC-prüfenden Endpunkt mit unabhängigen Event-Loops direkt auf.
Damit blockiert nicht die vorgelagerte Datenbank-Ratenbegrenzung den absichtlich
angehaltenen Fachvorgang. Die übrigen HTTP-/Signatur-/Größenfälle laufen über
TestClient und die bestehende Middleware; deren Regressionen stehen zusätzlich
in der Gesamtsuite. Das ist ein gezielter Transaktionsnachweis, kein Lasttest.

Die Vorprüfungen waren zunächst nicht erfolgreich: alte Payload-Fiktionen ohne
`field`/`object` oder mit fremder WABA wurden jetzt abgewiesen. Ihre Formate wurden
korrigiert. Die alte Anschluss-Assertion zählt jetzt zwei zurückgehaltene normale
Eingänge statt drei, weil `history` schon im Dispatcher ausgesondert wird.
Zusätzlich wurden ein falsches Sender-Testargument, die Annahme über die
werkstattgebundene URL-Auflösung und eine blockierende TestClient-Barriere
korrigiert. Keine zufälligen Sleeps oder automatischen Test-Retries wurden zur
Maskierung benutzt; nach den Korrekturen bestand die vollständige Suite.

Lokale Protokolle: `python312_postgres.log`, `postgres_bereinigung.json`,
`javascript.log`, `regressionen.log`. Der lokale Prüfstarter sperrt echten
`urllib`-Transport; die Tests verwenden synthetische Daten und ihre expliziten
Simulationen. Der Docker-Prüflauf bindet nur App, Tests, Templates, Rechtstexte,
Abhängigkeitsdateien und den Prüfstarter lesend ein, keine lokalen Zugangsdaten.

**Nicht geprüft:** echter Meta-Callback, Kontotrennung in einem realen Konto,
echte Zustellung, reale Kundennummer, reale Medien, produktive Last und visuelle
Browserabnahme. Keine vollständige Coexistence-Freigabe. Oberfläche und
Mandantenrechte wurden über die bestehenden HTTP-/Template-Tests geprüft.

## Nächster Schritt

Unabhängige Nachprüfung der beiden Korrekturen von Aufgabe 3.
