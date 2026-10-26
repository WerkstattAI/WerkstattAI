# M2.1: Verbindungsmodell und werkstattgebundener Zugang

Stand: 27. Oktober 2026. **Aufgabe 1 lokal implementiert; kein Kundenanschluss
und keine Coexistence-Freigabe.** Embedded Signup und verifizierte Übernahme von
Meta-Ergebnissen gehören ausdrücklich zum nächsten Arbeitsschritt.

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
- Änderungen vergleichen die erwartete Version unter Werkstattsperre;
  Widerruf erhöht die Version und entfernt den verschlüsselten Zugang.
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

## Tatsächlich ausgeführte Prüfungen

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

## Offene Grenze und genau ein nächster Schritt

Kein echter Meta-Test, Kundenanschluss, App-Review, Berechtigungswechsel,
Nummernregistrierung oder Deployment wurde durchgeführt. Das Modell bestätigt
keine Coexistence-Freigabe. Embedded Signup, die Übernahme verifizierter
Meta-Ergebnisse, Kontolebenszyklus, Telefon-Echos und Synchronisierung bleiben
offen; sie wurden nicht automatisch begonnen. Die übrigen Paket-/Betriebsfragen
aus dem Projektstand bleiben bestehen.

**Nächster Schritt:** Den serverseitig verifizierten Meta-Onboarding-Ablauf
für den angemeldeten Werkstattinhaber auf dieses Modell aufbauen, weiterhin
zunächst mit isolierten Daten und simuliertem Transport.
