# M2.1: Verbindungsmodell und werkstattgebundener Zugang

Stand: 27. Oktober 2026, nach Korrektur zweier unabhängiger Prüfbefunde.
**Aufgabe 1 lokal implementiert; unabhängige Nachprüfung steht aus. Kein
Kundenanschluss und keine Coexistence-Freigabe.** Aufgabe 2 und Embedded Signup
werden erst nach dieser Nachprüfung weiterverfolgt.

## Ausgangspunkt und wiederverwendete Funktionen

Der Arbeitsbaum war vor Beginn sauber auf
`codex/m1-whatsapp-pruefung-2026-10-21` (`5e9f473`). Nach `git fetch origin`
wurde der aktuelle Berichtsstand
`0ab6da9b47a2f70490ed2cdd5baea46c511b0d33` auf der eigenen Aufgabenbranch
`codex/m2-verbindungsmodell-2026-10-27` übernommen. Gegenüber dem zuvor
geprüften Anwendungscode `aa965e4` lagen nur Dokumentations-/Anweisungsänderungen
vor; `master` wurde nicht als Anwendungsbasis verwendet. Kein Reset, Merge
oder Force-Push; vorhandene M1-/M2-Berichte bleiben erhalten.

Gelesen wurden `AGENTS.md`, der aktuelle Projektstand, der M1-Abschluss vom
26. Oktober und die M2-Coexistence-Vorprüfung. Ein früherer implementierter
M2-Teil war auf diesem Quellstand nicht vorhanden.

Weiterverwendet werden `users.workshop_id`, vorhandene Rollen und
Sitzungsprüfung, `workshops`, additive Migrationen, `atomic_database`, der
WhatsApp-Nachrichten-/Gesprächskern, dauerhafte Versandreservierungen,
24-Stunden-Fenster und geschützter Bildabruf. Die bereits vorhandene Ablehnung
mehrdeutiger Senderzuordnungen bleibt bestehen und wird um eine
Datenbankgarantie ergänzt. Es gibt kein zweites Benutzer- oder Ticketsystem.

## Ergänztes Modell und Eindeutigkeit

`app/whatsapp_verbindungen.py` verwaltet je Werkstatt einen Datensatz mit WABA,
Nummern-ID, Anzeigenummer, Herkunft, Autorisierung, Verbindungszustand,
separater Coexistence-Bereitschaft, Version und verschlüsseltem Zugang.
`workshops.whatsapp_phone_number_id` bleibt die kanonische Nummernreservierung;
die Verbindung enthält zusätzlich die zugehörige Momentaufnahme. Jede
Abweichung sperrt den Zugang. Eine WABA darf mehrere getrennte Nummern und
Werkstattverbindungen besitzen.

- Die Migration normalisiert leere bzw. von Leerraum umgebene Altwerte. Ein
  eindeutiger Ausdrucksindex auf `workshops` sowie die eindeutige Nummer im
  Verbindungsmodell schützen parallele Schreibvorgänge. Auch umgebende
  ASCII-Leerraumzeichen werden im Datenbankindex berücksichtigt.
- Doppelte Bestandszuordnungen führen vor einer Datenänderung zum bereinigten
  Fehler mit Anzahl der konfliktbehafteten Nummerngruppen. Keine Zuordnung
  wird gelöscht, ausgewählt oder erfolgreich autorisiert. Die Initialisierung
  wird abgebrochen; der Bestand muss anhand bestätigter Eigentumsnachweise
  durch den Betreiber geklärt werden. Automatische Reparatur wäre hier falsch.
- Die Übernahme des Altbestands wird einmalig markiert. Neustarts gewähren
  nachträglich eingetragenen Nummern keine Legacy-Berechtigung.
- Interne Entwürfe speichern Zugang und Reservierung atomar, bleiben aber
  `unbestaetigt`/`vorbereitet`, Coexistence bleibt gesperrt. Es existiert kein
  HTTP-Endpunkt und keine Produktfunktion zur synthetischen Bestätigung.
- Änderungen vergleichen die erwartete Version unter Werkstattsperre und
  nochmals atomar beim Schreiben der Verbindung. Beide Schreibwege prüfen die
  betroffene Zeilenzahl; Widerruf erhöht die Version und entfernt den verschlüsselten Zugang.
  Die Nummernreservierung bleibt erhalten. Ein künftiger Wechsel des
  Eigentümers braucht einen eigenen verifizierten Ablauf.

## Schutz des Zugangs

Die zusätzliche Laufzeitabhängigkeit `cryptography==50.0.2` ist gepinnt. Sie
unterstützt Python 3.12 und 3.14 und wurde in beiden Laufzeiten tatsächlich
verwendet. Die etablierte
[Fernet-Implementierung](https://cryptography.io/en/stable/fernet/) bietet
authentifizierte Verschlüsselung; es wurde kein eigenes Kryptoverfahren
gebaut. Versions-/Plattformangaben:
[PyPI-Veröffentlichung](https://pypi.org/project/cryptography/50.0.2/).

Der eigene Schlüssel kommt ausschließlich aus `WHATSAPP_ZUGANGSSCHLUESSEL`.
Er muss unabhängig erzeugt und in der Umgebungs-/Secret-Verwaltung gesichert
werden. `AUTH_SECRET` und `WHATSAPP_APP_SECRET` werden nicht als Ersatz
verwendet; ein identischer Wert wird abgelehnt. Fehlende, ungültige oder nicht
passende Schlüssel sperren den betroffenen Kundenzugang mit bereinigter
Meldung. Es gibt keinen Klartext- oder globalen Ersatz.

Das verschlüsselte Paket bindet den Token an Werkstatt, WABA, Nummer und
Version. Ein kopiertes Chiffrat funktioniert deshalb nicht in einer anderen
Verbindung. Statusausgaben erlauben nur ausgewählte Metadaten, keine Tokens
oder Chiffrate. Der Zugang und Schlüssel erscheinen nicht in `repr` der
zugehörigen Objekte. Kundendatenexporte übernehmen die Verbindungstabelle
nicht. Transportfehler und Meta-Antworten werden auf bereinigte Angaben und
die Nachrichtenkennung begrenzt; rohe Antworttexte werden nicht gespeichert.

Schlüsselerzeugung, sichere Hinterlegung, Schlüsselrotation und tatsächliche
Wiederherstellung sind betriebliche Aufgaben vor einem echten Anschluss.
In dieser Arbeit wurde keine reale Secret-Konfiguration geändert.

## Gemeinsamer Zugriff und gesperrte Schreibwege

`zugang_fuer_werkstatt` prüft vorhandene Werkstatt, `is_demo`, eindeutige
Nummernreservierung, konsistente Verbindungsdaten, Autorisierung, Zustand und
entschlüsselbare Zugangsdaten. Der Zugriff erfolgt für:

- automatische Antworten im Webhook;
- Ticketantworten, Ticketnotizen mit Versand und aktive Kundenmitteilungen;
- Antworten im unzugeordneten Posteingang und Testversand;
- Vorlagenversand;
- geschützten Bildabruf mit zusätzlichem Abgleich der Nummer der Nachricht.

Die gemeinsamen Text-/Vorlagensender lösen den Zugang unmittelbar vor dem
Transport erneut auf. Ihr alter Tokenparameter ist nur syntaktisch kompatibel
und gewährt keine Berechtigung. Kein Aufrufer in `app/` übergibt darüber den
globalen Token. Der frühere lokale Erfolg ohne Meta-Zugang wurde entfernt.
HTTP bleibt außerhalb der vorhandenen Datenbanktransaktionen. Ein bereits
begonnener externer HTTP-Aufruf kann durch nachträglichen Widerruf nicht
rückwirkend zurückgerufen werden.

Profil-, Admin-Anlage- und Admin-Bearbeitungsformulare dürfen Nummern und
Anzeigenummern nicht ändern. Nicht übergebene Angaben bleiben erhalten;
abweichende manipulierte Formularwerte werden auch serverseitig abgelehnt.
Die Oberfläche zeigt vorhandene Werte nur lesbar und in den Einstellungen
getrennt den gespeicherten Zugang, Autorisierung und Coexistence-Status.
Eine frei eingegebene Nummer ist kein Autorisierungsnachweis.

## Ausdrücklich begrenzte M1-Kompatibilität

Nur die bei der ersten Migration bereits vorhandene, nicht als Demo markierte
Standardwerkstatt mit exakt passender `WHATSAPP_DEFAULT_PHONE_NUMBER_ID`
erhält die Herkunft `m1_legacy` und Autorisierung `altbestand`. Der Resolver
fordert dieselbe Konfigurations-/Datenbankübereinstimmung erneut. Erst dann
darf er den bisherigen `WHATSAPP_ACCESS_TOKEN` nutzen. Ein Widerruf oder
eine abweichende Zuordnung sperrt auch diesen Pfad. Andere manuelle Altwerte
bleiben unbestätigt.

Die Unterscheidung erfolgt über `is_demo`, nicht über den historischen
Produktivnamen `demo-werkstatt`. Die öffentliche Demo bleibt gesperrt.
M1-Legacy wird ausdrücklich nicht als bestätigte Kundenautorisierung oder
Coexistence-Bereitschaft ausgewiesen.

Die tatsächlichen Konfigurationsbezüge wurden in `app/config.py`, der
Standardwerkstatt-Anlage in `app/db.py` und der Nummernauflösung geprüft.
Zusätzlich wurde die lokale `.env` ausschließlich auf Merkmale geprüft:
Standard und öffentliche Demo sind getrennt, der historische Produktivname
ist Standard; lokale M1-Nummer, M1-Token und Kundenschlüssel sind dort nicht
hinterlegt. Keine echten Werte ausgegeben oder aus früheren Logs übernommen.
Die produktive Zuordnung wurde in dieser Aufgabe nicht erneut abgefragt;
deren vorheriger Nachweis bleibt im M1-Bericht. Legacy ist hier synthetisch,
nicht nochmals gegen Meta oder die Produktionsdatenbank geprüft.

## Historische Prüfungen der Erstimplementierung (Commit `59252bb`)

Die folgenden Zahlen gehören zur Erstimplementierung und wurden nicht als
neuer Gesamtlauf der Korrekturen wiederholt. Deren neue Nachweise stehen unten.

**544 von 544 Python-Tests bestanden**, Python 3.12.13 mit den gepinnten
Anwendungs-/Testabhängigkeiten; keine übersprungenen Tests. Darin tatsächlich
ausgeführt: bestehender PostgreSQL-Kommunikations-/Migrationstest und neuer
PostgreSQL-Verbindungstest mit konkurrierender Nummernbelegung,
Transaktionsrollback bei Altduplikaten und konkurrierendem Versionswechsel.
Der Großteil der übrigen Anwendungstests verwendet temporäres SQLite, nicht
PostgreSQL; dies ist kein kompletter PostgreSQL-Anwendungs- oder Lasttest.

Zusätzlich bestanden unter Windows/Python 3.14.3: 72 gezielte Formular-/
Kommunikations-/Verbindungstests, 47 gezielte Verbindungs-/Zuverlässigkeits-/
Medien-/Formulartests und abschließend alle 17 neuen SQLite-Verbindungstests
sowie der angepasste Altduplikat-Routingtest. **35 von 35 JavaScript-Tests
bestanden** (`node --test tests/*.mjs`). Diese Gruppen überschneiden sich.
Die letzte Ergänzung betraf ausschließlich den expliziten Altinstallationsaufbau
in der Legacy-Fixture und die Wiederherstellung des echten Indexes im
Routingtest; die betroffenen Tests wurden erneut erfolgreich ausgeführt.

Alle fachlichen Testdaten und Credentials sind künstlich; SQLite-Dateien sind
temporär. PostgreSQL 18 läuft ausschließlich in einem neu erzeugten Container
mit temporärem Dateisystem und zufälligem Testpasswort. Der Testcontainer
bekommt ausgewählte Quellen lesbar eingebunden, keine `.env`, lokalen Daten
oder alten Protokolle. Der Teststarter blockiert echten HTTP-Transport.
Die Entfernung der Datenbank und des Testnetzes wurde bestätigt.

Nachgewiesene Fälle: idempotente Migration und bestehende Installation,
Altduplikate ohne Datenverlust, Leerraum/Leerwerte, parallele Nummernbelegung,
gemeinsame WABA mit zwei Werkstätten, fremde Zugriffe, öffentliche Demo,
historischer Produktivname, fehlender/widerrufener Zugang, Versionskonflikt,
fehlender/falscher Schlüssel, manipuliertes/fremdes Chiffrat, alle drei
Profilschreibwege, Medien mit fremder Nummer und fehlende Secret-Ausgabe in
Status, HTML, Export sowie Transportantworten.

Der erste vollständige Containerlauf bestand fachlich einschließlich beider
PostgreSQL-Tests, scheiterte aber an einem fehlenden eingebundenen AVV-Dokument.
Das Prüfskript wurde korrigiert und der vollständige Lauf wiederholt. Die
ersten lokalen Fehler durch alte Annahmen über manuelle Nummernvergabe wurden
in den betroffenen Fixtures/Erwartungen angepasst; Berechtigungs-, Gesprächs-
und Zeitfensterassertionen wurden nicht abgeschwächt.

Lokale Protokolle und Prüfscripte liegen ausschließlich unter dem von Git und
Docker ausgeschlossenen `artifacts/m2-verbindungsmodell/` beziehungsweise den
ebenfalls ignorierten `artifacts/m2-*.log`. `git diff --check` ist ohne Befund;
Diff und neue Dateien wurden auf Secret-Muster und gegen vorhandene lokale
Secretwerte geprüft. Keine Schlüssel, Kundendaten oder Prüfartefakte werden
versioniert. Die übrigen Branches blieben unverändert.

## Korrekturen nach unabhängiger Prüfung am 27. Oktober 2026

Ausgangsbranch und Arbeitsbaum wurden erneut geprüft: sauberer Stand
`59252bb465d1826d61334ceedec813a5b7e02479`, nach `git fetch origin` identisch
mit `origin/codex/m2-verbindungsmodell-2026-10-27`. Die Korrekturen liegen
auf `codex/m2-korrekturen-2026-10-27`; kein Rücksetzen auf `master`.
Der externe Reproduktionscode wurde gelesen, aber weder übernommen noch
gegen eine bestehende Datenbank ausgeführt.

### Versionskonflikt zwischen Entwurf und Widerruf

Ursache: Die Werkstattsperre des Entwurfs schützt nicht gegen den Widerruf,
der nur die Verbindung aktualisiert. Das anschließende bedingungslose
`ON CONFLICT DO UPDATE` konnte einen inzwischen bestätigten Widerruf mit
derselben Versionsnummer überschreiben und den verschlüsselten Token
wiederherstellen. Die frühere Parallelprüfung zweier Entwürfe erfasste
diese Kombination nicht.

Der Entwurf aktualisiert den Konfliktdatensatz jetzt nur bei weiterhin
passender erwarteter Version. Bei einer Zeilenzahl ungleich eins wird die
gesamte Transaktion einschließlich der bereits geschriebenen Nummer und
Anzeigenummer zurückgerollt. Der Widerruf besitzt bereits denselben bedingten
Versionswechsel mit Zeilenzahlprüfung und bleibt unverändert. Die Version
steigt nur für einen erfolgreichen Schreibvorgang. Ein bewusster Neuanschluss
mit der aktuellen Version nach Widerruf bleibt zulässig und unautorisiert.
Es wurden keine Sperren über HTTP und keine neue dauerhafte Widerrufsperre eingeführt.

Drei zusätzliche PostgreSQL-Tests steuern echte Produktfunktionen und
Transaktionen mit Thread-Ereignissen: Entwurf nach Versionslesen anhalten,
Widerruf vollständig bestätigen, alten Entwurf fortsetzen; gestarteten Widerruf
vor seinem Schreiben anhalten und zuerst den Entwurf bestätigen; zwei Entwürfe
an der Werkstattsperre geordnet konkurrieren lassen. Es gibt keine zufälligen
Schlafpausen. Geprüft werden Erfolg/Ablehnung, monotone Versionen, Token und
Zustand sowie Nummern-/Anzeigenummernbindung. Im ersten Fall wird ausdrücklich
nachgewiesen, dass die Nummer bereits geschrieben wurde und der Rollback den
gesamten bestätigten Bestand erhält. SQLite prüft zusätzlich den abgelehnten
alten Entwurf und den zulässigen späteren Neuanschluss.

### Sichere Meta-Fehlerdiagnose

Ursache: Die bisherige Bereinigung entfernte mit den fremden Antworttexten
auch den diagnostisch wichtigen Code, etwa `133010`. Text- und Vorlagenversand
verwenden jetzt dieselbe HTTP-Fehlerbehandlung. Deren explizite Positivliste
übernimmt ausschließlich `error.code` und `error.error_subcode` als nichtnegative
Ganzzahlen; boolesche Werte, Strings und Gleitkommazahlen werden abgelehnt.
Unbekannte Felder, Providertexte, `error_data`, Header und URLs werden verworfen.
Ungültiges JSON, unlesbare oder über 64 KiB große Antworten führen zur sicheren
HTTP-Statusmeldung. Der Status bleibt auch bei fehlgeschlagenem Lesen erhalten.

Der Oberflächenformatierer verwendet dieselbe Typprüfung und lokal formulierten
Text, sodass Code und Subcode auch ohne fremde Meldung sichtbar sind.
Die Tests prüfen beide Versandarten mit synthetischem HTTP 400, Code `133010`,
Subcode und Token im Fremdtext bis zum dauerhaften Versandergebnis und
Oberflächenformatierer. Ergebnis, gespeicherte Nachricht, Ausgabe und
Anwendungslogs enthalten keinen fremden Text oder Token. Falsche Typen,
ungültiges JSON, Antwortgrößenlimit und Lesefehler werden zusätzlich geprüft.
HTTP 400/429/503 und unbekannter Netzwerkstatus behalten ihre Bedeutung;
die bestehenden Wiederholungs- und Unknown-Tests bleiben maßgeblich.

### Neu ausgeführte Prüfungen der Korrekturen

1. Zuerst **22/22 gezielte SQLite-Tests** unter Windows/Python 3.14.3:
   `test_whatsapp_verbindungen` (17) und `test_whatsapp_fehlerdiagnose` (5).
   Die bestehenden Tests gegen Token-Lecks wurden erhalten und mit ausgeführt.
2. Danach **4/4 PostgreSQL-Verbindungstests** unter Python 3.12.13/PostgreSQL 18:
   `test_whatsapp_verbindungen_postgres`, einschließlich der drei neuen
   deterministischen Konkurrenztests. Keine übersprungenen Tests.
3. Anschließend **396/396 Kommunikations-/Sicherheitsprüfungen** unter Python
   3.12.13, ohne übersprungene Tests. Darin der bestehende
   `test_communication_postgres` tatsächlich auf PostgreSQL 18; die übrigen
   Prüfungen verwenden SQLite oder benötigen keine Datenbank. Ausgeführte Module:

   ```text
   test_communication_dispatch test_communication_model test_communication_postgres
   test_communication_routing test_communication_transport test_communication_ui
   test_conversation_flows test_whatsapp_reliability test_dispatch_recovery
   test_dispatch_finalization test_manual_communication_forms test_whatsapp_medien
   test_customer_authorization test_customer_handoff test_auth_revocation
   test_http_security test_web_session_security test_privacy test_database_lifecycle
   test_workshop_communication_fixes test_whatsapp_fehlerdiagnose
   ```

Die fünf Fehlerdiagnosetests liefen damit auf beiden Python-Versionen; die
Gruppen dürfen nicht zu einer Anzahl unterschiedlicher Tests addiert werden.
Die alten 544 Python- und 35 JavaScript-Tests wurden nicht als vollständige
Gesamtsuiten erneut ausgeführt. Unveränderte JavaScript-, Intake- und
Dashboard-Workflow-Suiten gehören nicht zum neuen Prüfnachweis.

Alle Daten sind synthetisch. PostgreSQL läuft ausschließlich in einem neu
angelegten Wegwerfcontainer mit temporärem Dateisystem und zufälligem Testpasswort.
Der Python-Container bindet ausgewählte Quellen nur lesbar ein, keine `.env`
oder lokalen Daten. Echter HTTP-Transport ist während der Tests gesperrt.
Die Entfernung beider nacheinander angelegten Datenbanken und Testnetze wurde
bestätigt. `git diff --check`, Diffprüfung und Scan aller acht geänderten/neuen
Dateien auf Secret-Muster und vorhandene lokale Secretwerte waren ohne Befund.
Lokale Skripte und Protokolle unter `artifacts/m2-korrekturen/` und
`artifacts/m2-korrekturen-sqlite.log` bleiben durch Git und Docker ausgeschlossen.

## Offene Grenze und genau ein nächster Schritt

Kein echter Meta-Test, Kundenanschluss, App-Review, Berechtigungswechsel,
Nummernregistrierung oder Deployment wurde durchgeführt. Das Modell bestätigt
keine Coexistence-Freigabe. Embedded Signup, die Übernahme verifizierter
Meta-Ergebnisse, Kontolebenszyklus, Telefon-Echos und Synchronisierung bleiben
offen; sie wurden nicht automatisch begonnen. Die übrigen Paket-/Betriebsfragen
aus dem Projektstand bleiben bestehen.

**Nächster Schritt:** Unabhängige Nachprüfung beider Korrekturen vor Aufgabe 2.
