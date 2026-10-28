# WerkstattAI – Projektstand und nächste Schritte

## Aktueller Stand vom 28. Oktober 2026

**M2, Aufgabe 3: Die beiden unabhängig nachgewiesenen Echo-Fehler sind korrigiert.**
Ausgangspunkt war `123f807ce0c8a5d1905f9c9d949576296c6fd2cd`, lokal und remote
identisch bei sauberem Arbeitsbaum. Eigene Branch:
`codex/m2-business-app-korrekturen-2026-10-28`.

Eine ausdrückliche Assistentenfreigabe besitzt jetzt einen eigenen dauerhaften
Zeitpunkt in der bestehenden Gesprächskontrolle. Ein bisher ungesehenes,
eindeutig älteres Echo bleibt sichtbar, übernimmt aber nicht erneut und erzeugt
keine Ticketnotiz. Neue Telefonantworten dürfen weiterhin übernehmen. Dieselbe
Sekunde bleibt ohne erfundene Reihenfolge prüfpflichtig. Automatische
Wiederherstellung nach Versandfehlern setzt keinen manuellen Freigabezeitpunkt.

Recovery `sent` ohne Provider-ID klärt weiterhin nur den Versandstatus. Ein
solcher Kandidat bleibt bei der Echo-Zuordnung relevant; die Ungewissheit wird
nicht in eine zusätzliche Werkstattaktion umgewandelt. Eine später belegte
Provider-ID desselben Transportversuchs kann die ursprüngliche Sendung und das
Echo zusammenführen, ohne fachliche Wirkungen zu wiederholen. Bewusstes
Fortsetzen nach Prüfung bleibt möglich; `sending/unknown` wird nicht umgangen.

Die beiden unabhängigen Gegenproben wurden mit unveränderten Methodenrümpfen
und Assertions übernommen. Ergänzungen prüfen insbesondere die erste verspätete
Zustellung, Parallelität, Prozessneustart, Ticketfreigabe, Recovery, spätere
Provider-Zuordnung und Werkstatttrennung. Ursachen, Nachweise und Grenzen stehen
im [aktualisierten Bericht](m2-business-app-ereignisse-2026-10-28.md).

Neu bestanden: **650/650 Python-Tests**, darin **35 PostgreSQL-Tests**, ohne
Auslassungen. Python **3.12.13**, SQLite **3.46.1**, PostgreSQL **18.6** und
psycopg **3.2.3** auf einer frischen leeren Wegwerfdatenbank. Zusätzlich bestanden
**126/126 gezielte Python-Regressionen** mit Python **3.14.3** und **58/58
JavaScript-Tests** mit Node.js **24.16.0**. Gruppen überlappen. Prüfcontainer und
Prüfnetz wurden entfernt; lokale Nachweise liegen im ignorierten Verzeichnis
`artifacts/m2-business-app-korrekturen/`.

`coexistence_bereit=0`, HMAC, Dispatcher, Konto-/Nummernbindung, gezielter und
kontoweiter Widerruf sowie Versand-/Medien- und Recovery-Sperren bleiben erhalten.
Kein realer Meta-Test und keine vollständige Coexistence-Freigabe. Keine echten
Nachrichten, Kundenanschlüsse, Produktion, Meta-Konfiguration, Merge oder
Deployment. Aufgabe 4 wurde nicht begonnen.

### Nächste Schritte

1. **Unabhängige Nachprüfung der beiden Korrekturen von Aufgabe 3.**

## Historischer Stand der M2.3-Erstimplementierung vom 28. Oktober 2026

**M2, Aufgabe 3: Business-App-Echos und Kontolebenszyklus lokal implementiert und
mit simuliertem Meta-Transport geprüft. Aufgabe 2 ist unabhängig lokal abgenommen.**
Ausgangspunkt war `533c7aeb41db9e7acf07a3bc50615d4fc8c77305`, lokal und remote
identisch bei sauberem Arbeitsbaum. Eigene Branch:
`codex/m2-business-app-ereignisse-2026-10-28`.

Der Dispatcher trennt normale Nachrichten/Status, `smb_message_echoes`,
`account_update` und die reservierten Importfelder. Telefonantworten erscheinen
einmalig als ausgehende Werkstattnachrichten, übernehmen die Unterhaltung und
verändern weder offene Fragen noch Reparaturstatus. Frühe Echos und Status
werden mit der vorhandenen Versandfinalisierung abgeglichen; ungeklärter Versand
bleibt reserviert. Duplikate übernehmen nach bewusstem Fortsetzen nicht erneut.

Dokumentierte Kontoereignisse sperren ausschließlich die betroffene Nummer oder
die Verbindungen der betroffenen WABA über die bestehende Widerrufslogik. Neue
Verbindungsversionen und verspätete Ereignisse werden abgeglichen. Zeitlich
uneindeutige Kontoereignisse sperren Zugang und Automatik versionsgebunden bis
zum erneut verifizierten Anschluss. Versand und Medien verwenden denselben
geschützten Resolver. Neue Coexistence-Verbindungen bleiben `coexistence_bereit=0`;
normale zurückgehaltene Eingänge bleiben dauerhaft von Nachverarbeitung ausgeschlossen.

Neu tatsächlich bestanden: **618/618 Python-Tests**, darin **19 PostgreSQL-18-Tests**
auf eigens angelegter leerer Wegwerfdatenbank, keine Auslassungen, Python 3.12.13.
Zusätzlich **58/58 JavaScript-Tests** mit Node.js 24.16.0 sowie zuvor **66/66
gezielte Python-Regressionen** mit Python 3.14.3. Gruppen überlappen. Die neuen
Konkurrenzfälle verwenden Events/Barrieren, einschließlich Reservierung und
Neuanschluss; ein separater Python-Prozess prüft die dauerhafte Echo-Entscheidung.
Prüfdatenbank und Netz wurden entfernt. Diff und Geheimnisse ohne Befund.

Details, Primärquellen, korrigierte Testfiktionen und Grenzen stehen im
[Bericht zu Aufgabe 3](m2-business-app-ereignisse-2026-10-28.md). Reale Meta-Ereignisse,
Kundennummern und produktive Coexistence bleiben ungeprüft. Keine echten Nachrichten,
Kontoeinstellungen, Produktion, Registrierung, Merge oder Deployment. Bereits
gestartete externe HTTP-Aufrufe sind nicht rückholbar; keine globale
Exactly-once-Garantie. Aufgabe 4 wurde nicht begonnen.

### Damals vorgesehener nächster Schritt (Nachprüfung ergab zwei Korrekturen)

1. **Unabhängige Nachprüfung von Aufgabe 3.**

## Historischer Stand der letzten M2.2-Korrektur vom 28. Oktober 2026

**M2, Aufgabe 2: Der nachgewiesene Fehler beim späten Abbruch ist korrigiert.**
Ausgangspunkt war `e67ea2ea70ebf8926add448900880bd1521f39b4`, lokal und remote
identisch bei sauberem Arbeitsbaum. Die vorherigen Korrekturen wurden unabhängig
bestätigt. Eigene Branch: `codex/m2-signup-abbruch-2026-10-28`.

Abbruchdienst und Route liefern jetzt den tatsächlich in der gemeinsamen
Transaktion ermittelten Status. Gewinnt der Abbruch vor der dauerhaften
Bestätigung, bleibt der Versuch abgebrochen und ein späterer Abschluss gesperrt.
Ist der Anschluss bereits committed, meldet auch die Abbruchantwort den
abgeschlossenen Anschluss. Bereits bestätigte Zugänge werden nicht verändert
oder stillschweigend widerrufen. Nach Widerruf oder Neuanschluss liefert die
vorhandene Versionsprüfung für einen alten Abschluss weiterhin `ueberholt`.

Die Oberfläche übernimmt den maßgeblichen Ausgang der Abbruchanfrage; ihre
vorhandene Laufbindung schützt weiterhin vor alten Antworten. Zwei neue
Frontend-Regressionen prüfen den sichtbaren Abschluss sowie eine verspätete
Abbruchantwort nach Start eines neuen Versuchs. Die unabhängige Gegenprobe
wurde mit unverändertem Methodenrumpf und unveränderten Assertions übernommen.
Beide Abbruch-/Abschlussreihenfolgen werden mit Events kontrolliert, zusätzlich
auch unter PostgreSQL. Ein weiterer Test prüft Widerruf und Neuanschluss ohne
unbeabsichtigte Änderung von Verbindung oder Zugang.

Neu bestanden: **591/591 Python-Tests**, darin **14 PostgreSQL-18-Tests** auf
eigener leerer Wegwerf-Datenbank, ohne übersprungene Tests. Zusätzlich **56/56
gezielte Anschluss-/Auth-/Versionsregressionen** und **58/58 JavaScript-Tests**.
Beide Abbruch-/Abschlussreihenfolgen sowie Widerruf/Neuanschluss wurden auf SQLite
und PostgreSQL geprüft. Gruppen überlappen; keine automatischen Wiederholungen.
Testdatenbank und Testnetz wurden entfernt, Diff- und Geheimnisprüfung ohne Befund.
Der unveränderte Chrome-/SDK-Vertragsnachweis wurde hier nicht erneut ausgeführt.
Details stehen im [Embedded-Signup-Bericht](m2-embedded-signup-2026-10-27.md).
Lokale Prüfartefakte bleiben außerhalb von Git und Docker-Images.

`coexistence_bereit=0`, Automatik-Sperren, verschlüsselte Zugangsspeicherung,
Einmalcodes und HTTP außerhalb von Datenbanksperren bleiben erhalten. Reales
Meta-Onboarding und produktive Coexistence bleiben ungeprüft. Keine Produktion,
echten Nachrichten, Kontoeinstellungen, Registrierung, Merge oder Deployment.
Aufgabe 3 wurde nicht begonnen.

### Damals vorgesehener nächster Schritt (inzwischen unabhängig abgenommen)

1. **Unabhängige Nachprüfung dieser letzten Korrektur vor Abschluss von Aufgabe 2.**

## Historischer Stand nach den M2.2-Korrekturen vom 27. Oktober 2026

**M2, Aufgabe 2: Korrekturen nach der unabhängigen Nachprüfung lokal umgesetzt
und geprüft. Keine reale Meta-Zulassung oder Coexistence-Betriebsfreigabe.**
Ausgangspunkt: sauberer Arbeitsbaum und identischer Remote-Commit `841db3f`.
Eigene Korrekturbranch: `codex/m2-signup-korrekturen-2026-10-27`.

Beide granularen WhatsApp-Berechtigungen müssen nun das ausgewählte Konto
abdecken. Ein vorhandener uneingeschränkter Scope wird von einem fehlenden
Eintrag unterschieden. Fremde, leere und fehlerhafte Ziele werden vor dem
Abonnement zurückgewiesen. Browser-Operationen sind an ihren eigenen Lauf
gebunden; alte Antworten, Fehler, Timer und Abschlussblöcke überschreiben
keinen neuen Versuch. Die Anschluss-CSP erlaubt gezielt den tatsächlich
benötigten SDK-Konfigurationsabruf. Das dokumentierte Session-Schema `"3"`
wird ausdrücklich angefordert; Signup v4 und strikte Ereignisprüfung bleiben.
Verbindungsmodell, Verschlüsselung, Versionsschutz und Automatik-Sperren bleiben
erhalten, insbesondere `coexistence_bereit=0` und der begrenzte M1-Legacy-Pfad.

Neu bestanden: **585/585 Python-Tests**, darunter **elf PostgreSQL-18-Tests**
auf eigener Wegwerf-Datenbank, ohne übersprungene Tests. Zusätzlich **151/151
gezielte Python-Tests**, **56/56 JavaScript-Tests**, die drei ursprünglichen
Zusatzgegenproben und ein Chrome-Test mit echtem lokal ausgeliefertem SDK,
aktiver CSP und vollständig abgefangenen Browser-Anfragen. Gruppen überlappen.
Ein anfänglicher falscher Testmodulname verursachte einen dokumentierten
Importfehler; korrigierter Starter und vollständige Regression bestanden.

Der einmalige `KeyError` im unabhängigen Gesamtprüflauf wurde nicht erneut
beobachtet. Seine Ursache bleibt mangels damaligem Status/Antwortinhalt offen.
Verbesserte Assertions liefern jetzt eine sichere Diagnose; eine kontrollierte
Ablaufgegenprobe belegt nur einen möglichen Antworttyp, keine rückwirkende Ursache.
Details, Quellen und lokale Testanleitung im
[Embedded-Signup-Bericht](m2-embedded-signup-2026-10-27.md).

Keine Produktion, echten Nachrichten, Meta-Kontoeinstellungen, Registrierung,
Rechtevergabe, Merge oder Deployment. Reale Meta-Anmeldung, erfolgreicher Callback
und Kundennummer bleiben ungeprüft. Aufgabe 3 wurde nicht begonnen.

### Damals vorgesehener nächster Schritt (inzwischen unabhängig nachgeprüft)

1. **Unabhängige Nachprüfung der Korrekturen von Aufgabe 2.**

## Historischer Stand der M2.2-Erstimplementierung vom 27. Oktober 2026

**M2, Aufgabe 2: Die autorisierte Embedded-Signup-Anschlusskette ist lokal
implementiert und mit simuliertem Meta-HTTP geprüft. Kein realer Kundenanschluss
und keine Coexistence-Betriebsfreigabe.** Ausgangspunkt war der unabhängig
nachgeprüfte Commit `2569f57`; Arbeitsbaum und Remote waren identisch und sauber.
Die Änderungen liegen auf `codex/m2-embedded-signup-2026-10-27`.

Der bestehende Verbindungs-/Fernet-/Versionskern bleibt die einzige
Zugangsverwaltung. Ergänzt wurden der Dashboard-Einstieg, sitzungsgebundene
kurzlebige Einmalversuche, serverseitiger Codeaustausch, Konto-/Nummern- und
Tokenprüfung sowie bestätigtes Abonnement der App am Kundenkonto. Browser-Erfolg
allein autorisiert nichts. Abbruch, Logout, Rollenverlust, abgelaufene oder
wiederverwendete Kennungen/Codes, konkurrierende Abschlüsse und spätere Widerrufe
werden kontrolliert behandelt. Teilfehler bleiben unbestätigt; Abonnementprüfung
kann ohne erneuten Codeaustausch fortgesetzt werden.

Neue Coexistence-Verbindungen bleiben serverseitig für Automatik gesperrt.
Nicht freigegebene Eingänge werden einmalig mit Kennung und Sperrgrund erfasst
und ohne Wiederholungsfehler quittiert; keine Ticket-/Intake-Änderung und kein
neues 24-Stunden-Fenster. Vorbereitete automatische Antworten werden ebenfalls
unterdrückt. Der begrenzte M1-Legacy-Pfad bleibt erhalten. Die Oberfläche trennt
autorisierte Zugänge von der noch fehlenden Betriebsbereitschaft.

Neu tatsächlich bestanden: **581 Python-Tests** unter Python 3.12.13, darin
**zehn PostgreSQL-18-Tests**, ohne übersprungene Tests. Zuvor gezielte SQLite-
und PostgreSQL-Läufe; nach letzten Ergänzungen 100 gezielte Kommunikations-/
Anschlusstests und 42 Anschluss-/Verbindungstests unter Windows/Python 3.14.3.
Abschließend zehn gezielte PostgreSQL-Tests einschließlich eines zusätzlichen
Konkurrenztests für Logout und dauerhaften Abschluss; die Versuchzeile wird
beim Abschluss bis zum Transaktionsende gesperrt.
**42 JavaScript-Tests bestanden.** Die Gruppen überschneiden sich.
Nachweise, geprüfte offizielle Quellen, Konfigurationsnamen, lokale Testanleitung
und offene externe Voraussetzungen stehen im
[Embedded-Signup-Bericht](m2-embedded-signup-2026-10-27.md).

Die realen Meta-Freigaben, App-Konfiguration, SDK-/Popup-Durchlauf und
Kundennummer wurden nicht geprüft oder verändert. Kein Merge oder Deployment.
Keine echten Nachrichten, Registrierung oder Rechtevergabe. Aufgabe 3 wurde
nicht begonnen; Echo-/Historien-/Synchronisierungsschutz bleibt offen.

### Damals vorgesehener nächster Schritt (inzwischen unabhängig nachgeprüft)

1. **Unabhängige Nachprüfung des Anschlussprozesses vor Aufgabe 3.**

## Historischer Stand nach den M2.1-Korrekturen vom 27. Oktober 2026

**Zwei unabhängig gefundene Fehler in M2, Aufgabe 1 sind lokal korrigiert;
die unabhängige Nachprüfung steht aus. Aufgabe 2 wurde nicht begonnen.**
Ausgangsstand war der saubere Commit `59252bb` der bisherigen M2-Branch,
nach Abruf der Remote-Referenzen unverändert. Die Korrekturen liegen auf
`codex/m2-korrekturen-2026-10-27`.

Ein bereits gelesener Verbindungsentwurf konnte durch bedingungsloses Schreiben
einen inzwischen bestätigten Widerruf überschreiben. Der Entwurf prüft jetzt
die Version atomar beim Schreiben und die betroffene Zeilenzahl, wie bereits
der Widerruf. Ein Konflikt rollt auch die Nummern-/Anzeigenummernänderung zurück.
Ein späterer bewusster Neuanschluss mit aktueller Version bleibt möglich.

Die HTTP-Fehlerbereinigung hatte auch sichere Meta-Codes entfernt. Text und
Vorlagen übernehmen jetzt gemeinsam nur streng ganzzahlige Codes und Subcodes;
Providertexte, Rohantworten, Header und URLs werden verworfen. Die Oberfläche
zeigt die Codes mit lokalem Text. HTTP-Status und Unknown-Semantik bleiben erhalten.

Neu bestanden: zuerst **22 SQLite-Tests** unter Windows/Python 3.14.3, danach
**4 PostgreSQL-18-Verbindungstests** unter Python 3.12.13, darunter drei
deterministisch koordinierte Konkurrenztests. Anschließend bestanden
**396 Kommunikations-/Sicherheitsprüfungen** unter Python 3.12.13 einschließlich
des bestehenden PostgreSQL-Kommunikationstests; keine übersprungenen Tests.
Die Gruppen überschneiden sich bei fünf Fehlerdiagnosetests. Der
[M2.1-Bericht](m2-verbindungsmodell-2026-10-27.md) trennt diese Nachweise von den
historischen Zahlen der Erstimplementierung. Ausschließlich synthetische Daten
und isolierte Wegwerf-Datenbanken; echter HTTP-Transport in Tests gesperrt.
Datenbanken und Testnetze wurden entfernt. Diff- und Geheimnisprüfung ohne Befund.
Keine Produktion, Meta-Aufrufe, realen Nachrichten, Registrierung, Merge oder
Deployment. Die bisherigen M1-Nachweise bleiben unverändert.

### Damals vorgesehener nächster Schritt (inzwischen unabhängig nachgeprüft)

1. **Unabhängige Nachprüfung beider Korrekturen vor Aufgabe 2.** Embedded Signup
   und weitere M2-Arbeiten erst danach fortsetzen; hier nicht automatisch beginnen.

## Historischer Stand der M2.1-Erstimplementierung vom 27. Oktober 2026

**M2, Aufgabe 1 ist lokal umgesetzt: Verbindungsmodell und werkstattgebundener
Zugang. Kein echter Kundenanschluss und keine Coexistence-Freigabe.**
Die additive Migration sichert eindeutige Nummernreservierungen auch auf
Datenbankebene, erhält Altzuordnungen und sperrt mehrdeutige Bestandsdaten.
Kundenzugänge sind mit eigenem Umgebungsschlüssel authentifiziert
verschlüsselt. Gespeicherter Zugang, bestätigte Autorisierung und
Coexistence-Bereitschaft bleiben getrennt.

Automatische und manuelle Antworten, Testversand, Vorlagen und geschützter
Bildabruf verwenden den gemeinsamen werkstattgebundenen Zugriff. Neue,
widerrufene oder widersprüchliche Verbindungen erben keinen globalen Token.
Nur die einmalig festgehaltene, exakt zur Konfiguration passende eigene
M1-Zuordnung besitzt einen begrenzten Legacy-Pfad; die öffentliche Demo ist
über `is_demo` gesperrt. Profil- und Adminformulare dürfen keine Nummern
zuweisen oder ändern. Ein interner Entwurf erteilt keine Autorisierung.

544 Python-Tests unter Python 3.12.13 einschließlich zweier tatsächlich
ausgeführter PostgreSQL-18-Integrationstests sowie 35 JavaScript-Tests bestanden.
Gezielte SQLite-Tests liefen zusätzlich unter Windows/Python 3.14.3.
Prüfnachweise und Grenzen stehen im
[M2-Verbindungsmodell-Bericht](m2-verbindungsmodell-2026-10-27.md).
Es wurden keine Produktionsdatenbank, Meta-Kontoeinstellungen oder realen
Nachrichten verwendet und kein Deployment durchgeführt. Die Änderungen
liegen auf der eigenen Branch `codex/m2-verbindungsmodell-2026-10-27`.
Der zuvor dokumentierte M1-Abschluss bleibt bestehen.

### Damals vorgesehene Folgeschritte (vor der unabhängigen Prüfung)

1. **Den serverseitig verifizierten Meta-Onboarding-Ablauf implementieren.**
   Den angemeldeten Werkstattinhaber und die von Meta bestätigten Assets
   zuverlässig mit dem neuen Modell verbinden; zunächst weiter mit isolierten
   Daten und simuliertem Transport prüfen. Diese Aufgabe wurde hier noch nicht
   begonnen. Der vollständige Embedded Signup und echte Kundenanschluss bleiben
   offen; fehlende Meta-Freigaben blockieren unabhängige lokale Arbeit nicht.
2. **Anschließend die weiteren M2-Teile:** Kontolebenszyklus, Telefon-Echos,
   Übernahme und Synchronisierung ergänzen; erst danach mit ausdrücklich
   autorisierten Werkstätten real prüfen. Anbieter-/Unternehmensfreigaben
   parallel vorbereiten. M1 bestätigt keine externen Nummern oder Coexistence.
3. **Danach Produktaufgaben und Pilotvorbereitung:** W1, N1, D1, S1 und P1
   anhand des Projektzentrums neu bewerten. Paketabsicherung, Backup und
   Wiederherstellung, Fehlerüberwachung sowie Betriebsunterlagen bleiben vor
   einem Pilot erforderlich. Das Administratorpasswort wird erst kurz vor dem
   Pilotbetrieb geändert; Mikolaj speichert es selbst.

## Historischer Stand vom 26. Oktober 2026

**M1 ist abgeschlossen; als Nächstes folgt M2, die Anbindung von Werkstätten.**
Die Meta-Testnummer wurde nach dem nachgewiesenen Fehler 133010 erneut
registriert. Vorlagenversand, neuer Texteingang, manueller Anwendungsversand
mit bestätigtem Telefonempfang und echter geschützter JPEG-Abruf funktionieren
im beobachteten Ablauf. Mikolaj bestätigte das Foto im Posteingang und Ticket.

Der frühere Grundablauf mit Ticketanlage und automatischer Antwort beruht auf
Mikolajs Bestätigung vom 23. Oktober; Datum und Version dieses früheren Tests
sind unbekannt. Die neue Prüfung nutzte eine bereits manuelle Unterhaltung.
Sie bestätigt das Ausbleiben der Automatik nach weiterem Eingang, aber keinen
neuen Übernahme-Klick oder vollständig neuen Ablauf auf frischem Kontakt.
Einzelheiten und Quellen: [M1-Ergebnis](m1-whatsapp-pruefung-2026-10-26.md).

**GET-Nachprüfung am 26. Oktober geklärt:** Die zunächst beobachteten 403
stammten von Cloudflare 1010 gegen den Standard-Client des Prüfskripts.
Mit offen ausgewiesenem Prüfclient liefern öffentlicher Callback und Backend
jeweils 200 und die identische Challenge; absichtlich falsche Tokens werden
an beiden Endpunkten abgelehnt. Es wurde keine Konfiguration geändert.
Der zuvor vermutete Konfigurationsfehler ist nicht nachgewiesen.
Details stehen im aktualisierten [M1-Ergebnis](m1-whatsapp-pruefung-2026-10-26.md).

Geprüfter Railway-Anwendungscommit:
`aa965e481f62ad34ee752d5b3cd89f365c4d30fb`, Deployment
`e81fee99-9838-4ee3-9639-ba2674b3537b`, `SUCCESS`.
Diese Aktualisierung ändert ausschließlich Dokumentation und löst kein neues
Anwendungsdeployment aus.

### M2-Vorprüfung vom 26. Oktober 2026

**Noch nicht anschlussbereit für die bestehende Business-App eines Kunden.**
Aktuell fehlen der freigegebene Tech-Provider-/Advanced-Access-Prozess,
eine Login-Konfiguration, der serverseitige Kunden-Onboarding-Ablauf und
ein Verbindungsmodell mit sicherem kundenbezogenem Tokenbezug. Telefon-Echos,
Kontolebenszyklus und Synchronisierung werden noch nicht verarbeitet.
Die entsprechenden Coexistence-Felder sind im Meta-Panel deaktiviert.

Ein isolierter Aufruf der Originalparser bestätigt: ein neues Textpaket wird
erkannt, ein Business-App-Echo nicht; ein historisches Medienpaket wird noch
nicht nach seinem Webhook-Feld getrennt. Die vorhandene Werkstatttrennung
und Ablehnung mehrdeutiger Sender sind eine Basis; Schreibschutz/eindeutige
Autorisierung der Nummernzuordnung fehlen. Für neue Implementierung v4 verwenden,
da Meta v2/v3 seit 15. Oktober als eingestellt ausweist.
Details und Abnahmekriterien: [M2-Vorprüfung](m2-coexistence-vorpruefung-2026-10-26.md).

### Historische nächste Schritte vom 26. Oktober 2026

1. **M2 umsetzen; Meta-Freigaben parallel vorbereiten.** Zuerst Verbindungsmodell,
   eindeutige autorisierte Nummernbindung, sicherer Tokenbezug und Embedded Signup;
   danach Telefon-Echos, Lebenszyklus und Synchronisierung. Anschließend mit
   ausdrücklich autorisierten Werkstätten real prüfen. Die GET-Nachprüfung
   ist geklärt; M1 bestätigt keine externen Nummern oder Coexistence.
2. **Danach die vereinbarten Produktaufgaben neu bewerten:** W1 Bedienung der
   Vorgänge, N1 endgültiger Name, D1 Dashboard mit Figma, S1 Website und
   Gespräche, P1 betreuter Pilot. Den aktuellen Arbeitsplan führt das
   Notion-Projektzentrum.
3. **Vor dem Pilotbetrieb:** Paketabsicherung, Backup und Wiederherstellung,
   Fehlerüberwachung und Betriebsunterlagen erledigen. Administratorpasswort
   kurz vor dem Pilotbetrieb ändern; Mikolaj speichert es selbst.
   Unternehmensformalitäten und Meta-Freigaben laufen parallel.

## Historischer Stand vom 21. Oktober 2026

**M1 ist offen und wartet auf die Teilnahme mit einem bestätigten eigenen
WhatsApp-Testempfänger.** Mikolaj hat am 21. Oktober gebeten, zunächst alle
unabhängigen Prüfungen zu erledigen und den Telefontest später durchzuführen.
Es wurde keine echte Testnachricht versendet. Der tatsächliche Empfang,
Ticketanlage, Mitarbeiterübernahme und der echte Meta-Bildabruf sind noch
nicht belegt. Bericht: [M1-WhatsApp-Prüfung](m1-whatsapp-pruefung-2026-10-21.md).

Die Anwendung und die Dashboard-Anmeldung wurden erneut erfolgreich geprüft.
Die `phone_number_id` der Standardwerkstatt stimmt mit der Konfiguration
überein. Meta meldet `CONNECTED`, einen gültigen Zugang mit den benötigten
Messaging-/Verwaltungsbereichen und ein aktives `messages`-App-Abonnement an
der passenden öffentlichen Webhook-Adresse. Beide gültigen
Webhook-Verifikationsabfragen waren erfolgreich. Diese Vorprüfungen belegen
noch keinen echten Nachrichteneingang oder eine Zustellung.

Railway meldet weiterhin Deployment
`e81fee99-9838-4ee3-9639-ba2674b3537b`, Status `SUCCESS`, Instanz `RUNNING`,
Anwendungscommit `aa965e481f62ad34ee752d5b3cd89f365c4d30fb`.
Ein zusätzlicher Dateivergleich in der laufenden Instanz war wegen eines
fehlenden lokalen SSH-Schlüssels nicht möglich. Der aktuelle Versionsnachweis
stammt aus Railway, nicht aus einem Versionsendpunkt der Anwendung.

Die Abweichung zwischen lokaler Dokumentation und GitHub ist geklärt:
Der aktuell abgefragte Remote-Branch `codex/kundenkommunikation-2026-09-26`
steht auf `aa965e4`; dessen Projektstand stammt vom 26. September. Lokal lagen
die beiden Dokumentationscommits `bd0a218` und `4e8b979` vom 19. Oktober darüber.
Die Anwendungsdateien unterscheiden sich zwischen diesen Ständen nicht.
Beide lokalen Commits bleiben im separaten M1-Prüfbranch
`codex/m1-whatsapp-pruefung-2026-10-21` erhalten.

Zusätzlich sind 26 gezielte lokale WhatsApp-/Medientests unter Python 3.14.3
bestanden. Sie verwenden temporäre SQLite-Daten und simulierten Transport.
Es wurde kein Produktfehler nachgewiesen und kein Anwendungscode geändert.
Lokale Prüfscripte, Protokolle und ein synthetisches PNG liegen ausschließlich
unter dem von Git und Docker ausgeschlossenen `artifacts/m1-2026-10-21/`.

### Historische nächste Schritte vom 21. Oktober 2026

Die neueren Nutzerentscheidungen ersetzen die Reihenfolge vom 19. Oktober:

1. **M1: vollständigen realen WhatsApp-Test durchführen.** Sobald Mikolaj am
   eigenen Telefon teilnehmen kann, Eigentum und Endziffern des Testempfängers
   bestätigen; anschließend Textannahme, genau ein Ticket, automatische und
   manuelle Zustellung, Mitarbeiterübernahme und ein synthetisches JPEG/PNG
   einschließlich geschütztem echtem Meta-Abruf prüfen. Bis zum Nachweis offen.
2. **Anbindung von Werkstätten bearbeiten.** Die erforderlichen Meta-Freigaben
   und den vollständigen Embedded-Signup mit Berechtigungs-/Tokenaustausch sowie
   werkstattspezifischer Zuordnung bearbeiten und mit autorisierten Werkstätten
   prüfen. M1 bestätigt weder Coexistence noch die Anbindung fremder Nummern.
3. **Betreuten Pilotbetrieb vorbereiten.** Paketabsicherung, Datensicherung und
   Wiederherstellung, Fehlerüberwachung sowie Anbieter-/Betriebsunterlagen bleiben
   vor dem Pilotbetrieb zu erledigen. Das Administratorpasswort wird kurz vor
   dem Pilotbetrieb geändert; Mikolaj speichert es selbst.
4. **Spätere Aufgaben zurückstellen.** Sprachnachrichten, Namensänderung,
   Figma-Design und weitere Funktionen folgen später.

## Historischer Stand vom 19. Oktober 2026

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

### Historische Reihenfolge vom 19. Oktober 2026 – überholt

Die damalige Vereinbarung führte fünf offene Arbeitspakete und stellte die
Punkte 1 und 2 voran. Sie wird als Historie bewahrt; für die weitere Arbeit
gilt die neue Reihenfolge vom 21. Oktober oben.

1. **Zugänge absichern und Abhängigkeiten aktualisieren.** Das Passwort des
   bestehenden Administratorkontos ändern und Pakete mit bekannten
   Sicherheitslücken als kompatiblen Satz aktualisieren. Anschließend die
   betroffenen Abläufe prüfen. Eine Änderung allein der Railway-Startvariable
   setzt das Passwort eines bestehenden Benutzers nicht zurück.
2. **Vollständigen WhatsApp-Test mit bestätigtem eigenem Empfänger durchführen.**
   Kundennachricht, Ticketanlage, Werkstattantwort und tatsächliche Zustellung
   prüfen. Ein synthetisches Beispielbild empfangen, im Posteingang und Ticket
   öffnen, die Unterhaltung an einen Mitarbeiter übergeben und kontrollieren,
   dass keine doppelten Nachrichten entstehen. Ein simulierter Transporttest
   ersetzt diesen tatsächlichen Ablauf nicht.
3. **Unternehmensdaten und Meta-Verifizierung abschließen.** Tatsächliche
   Unternehmensdaten und erforderliche Gewerbe-/Steuerfragen klären, die Angaben
   in Meta vervollständigen und Unternehmensverifizierung, Zugriffsverifizierung
   sowie App-Review für die Tech-Provider-Nutzung bearbeiten. Eine
   Gewerbeanmeldung allein schaltet die Meta-Freigaben nicht automatisch frei.
4. **Nummern externer Werkstätten anbinden.** Einen vollständigen
   Embedded-Signup-Prozess mit Zustimmung des Kontoinhabers, erforderlichem
   Berechtigungs-/Tokenaustausch und werkstattspezifischer Zuordnung umsetzen.
   Die getrennten Konten und Nachrichten mit autorisierten Testwerkstätten prüfen.
5. **Erstes betreutes Werkstatt-Deployment vorbereiten.** Datensicherung und
   tatsächliche Wiederherstellung prüfen, Fehlerüberwachung einrichten und das
   Konto der ersten Werkstatt einschließlich Profil, Anbieterangaben und
   abgestimmten Datenschutz-/Betriebsunterlagen vervollständigen. Erst nach
   den erforderlichen Nachweisen echte Kundendaten aufnehmen.

Der folgende historische Prüfumfang ist keine aktuelle Freigabe dieser offenen
Punkte. Erledigte Aufgaben weiterhin nur mit ihrem tatsächlichen Prüfnachweis
aktualisieren; die damalige Reihenfolge gilt nicht mehr als Arbeitsauftrag.

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
