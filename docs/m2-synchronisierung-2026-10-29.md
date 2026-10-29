# M2, Aufgabe 4: Historie, Kontakte und sichere Synchronisierung

Stand: 29. Oktober 2026. Lokale Implementierung mit synthetischen Werkstätten
und simuliertem Meta-Transport. Unabhängige Prüfung von Aufgabe 4 und realer
Meta-Anschluss stehen aus. `coexistence_bereit` bleibt 0. Keine Betriebsfreigabe.

## Ausgangspunkt

Ausgangspunkt: `326f0007e0c474481cd50005ae336e179aa3cfee`, sauberer Arbeitsbaum,
lokales HEAD und Remote unabhängig verglichen und identisch. Aufgabenbranch:
`codex/m2-synchronisierung-2026-10-29`.

Gelesen wurden `AGENTS.md`, Projektstand, Anschluss- und Ereignisbericht sowie
der unabhängige Bericht unter
`C:\Users\Mikolaj\Documents\New project\m2-business-app-korrektur-review-2026-10-28\PRUEFBERICHT.txt`.
Dieser nimmt Aufgabe 3 einschließlich beider Echo-Korrekturen lokal ab.
Seine 650 Python-Tests einschließlich 35 PostgreSQL-Fällen und 58 JavaScript-Tests
sind **historische Nachweise vom 28. Oktober**, keine Prüfung dieser Änderung.

## Am 29. Oktober erneut geprüfter Providervertrag

Öffentlicher Web-Abruf lieferte HTTP 429. Die Browser-Steuerung meldete keine
verfügbare Browseroberfläche. Ein anschließender öffentlicher HTML-Abruf mit
ausgewiesenem Client lieferte für Onboarding, History, State-Sync und Fehlercodes
jeweils HTTP 200; der eingebettete CMS-Inhalt wurde extrahiert und gelesen.
Die separat genannte `smb_app_data`-Referenz lieferte beim direkten Abruf HTTP 404,
auch mit englischer Locale. Aus diesem fehlenden Abruf wird kein zusätzlicher
Vertrag abgeleitet. Die POST-Syntax ist in der gelesenen Onboarding-Seite belegt.
Es gibt hier keinen implementierten GET-Statusabruf und keine angenommene
Provider-Idempotenz.

Quellen:

- [Business-App-Onboarding](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users)
- [SMB-App-Data-Edge, Abruf nicht erfolgreich](https://developers.facebook.com/docs/graph-api/reference/whats-app-business-account-to-number-current-status/smb_app_data)
- [History-Webhook](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/history/)
- [State-Sync-Webhook](https://developers.facebook.com/documentation/business-messaging/whatsapp/webhooks/reference/smb_app_state_sync/)
- [Fehlercodes](https://developers.facebook.com/documentation/business-messaging/whatsapp/support/error-codes)

| Gegenstand | Belegter Providervertrag | Lokale Umsetzung / verbleibendes Nichtwissen |
| --- | --- | --- |
| Initialisierung | POST `/<PHONE_NUMBER_ID>/smb_app_data`, `messaging_product=whatsapp`, getrennte `sync_type`-Werte `smb_app_state_sync` und `history`; je einmal | Zwei dauerhaft reservierte Schritte. `request_id` wird gespeichert; nur Annahmenachweis. Kein blindes Wiederholen. |
| Freigabeentscheidung | Teilen im Meta-/Business-App-Verfahren; History-Fehler 2593109 bedeutet nicht geteilt | Kein SDK-Consent-Feld. Signierte Verlaufsdaten belegen die konkrete Lieferung. Lokaler Verzicht verhindert die noch nicht gestartete History-Anforderung, ändert aber Meta nicht. |
| Abschluss Historie | `progress=100` bezeichnet Abschluss; `phase=2` allein genügt nicht; leere Phasen können ohne Callback bleiben | Monotones Maximum plus lückenlose bekannte Chunk-Folgen pro vorhandener Phase. Keine Pflicht zu allen drei Phasen, keine erfundene Gesamtzahl. Keine Lieferung ist kein Leer-Nachweis. |
| Abschluss Kontakte | `state_sync`, `action=add/remove`, Kontaktdaten und Änderungszeit; kein dokumentierter globaler Abschlussmarker | Technisch genügt der angenommene Kontaktauftrag ohne Prüfkonflikt, als eingerichteter Änderungsstrom. Kontaktvollständigkeit wird ausdrücklich nie behauptet. |
| Zeitgrenze | Onboarding nennt 24 Stunden ab Anschluss | Konservativer lokaler Beginn ist der Start des zugehörigen Signup-Versuchs, vor dem Meta-Flow (`ablauf - 600`). Wiederaufnahme verlängert nichts. Die tatsächliche Providerfrist kann nur Meta abschließend beurteilen. Altbestände ohne Nachweis erhalten keine neue Frist. |
| Fehler | 2593107: Einmalquote; 2593108: Zeitgrenze; 2593109: nicht geteilt | Eigene Zustände `quote`, `frist`, `nicht_geteilt`; sonst bereinigter numerischer Code und `fehler`/`unklar`. Kein automatisches Offboarding. |
| Medien | Platzhalter in Threads, separate `value.messages` unter `field=history`; nur begrenzte ältere Medien verfügbar | Metadaten nach Provider-ID verbinden, beide Reihenfolgen. Nachrichtenabschluss und Medienverfügbarkeit getrennt. Kein Download von Payload-URLs. |

Der Adapter verwendet unverändert `whatsapp_signup_graph_version`, im Projekt
standardmäßig **v26.0**, auch im simulierten HTTP-Vertrag geprüft. Signup-SDK,
Session-Schema und übrige API-Versionen werden nicht migriert. Die gelesenen
Referenzen beschreiben den aktuellen generischen Vertrag; ein realer Aufruf mit
v26.0 ist nicht nachgewiesen. Dokumentationskopien bleiben im ignorierten
Prüfverzeichnis und gehören nicht ins Image.

`chunk_order` wird als begrenzte nichtnegative Zahl akzeptiert. Für die lokale
Abschlussprüfung wird konservativ eine Folge 1 bis zum höchsten bekannten Teil
je gelieferter Phase verlangt, entsprechend der dokumentierten Beispiele.
Ein beginnender Teil 0 führt daher nicht zu einer erfundenen Abschlussfreigabe.
Neue bekannte Lücken oder widersprüchliche Wiederholungen sperren Bereitschaft.
Es gibt keinen Beweis für noch unbekannte, entgegen dem Abschlussindikator
später kommende Teile und keine globale Exactly-once-Zusage.

Bei Kontakten werden positive Providerzeiten geordnet; gleiche Zeiten mit
abweichendem Inhalt werden prüfpflichtig. Die Sonderwerte 0 und -1 besitzen in
den gelesenen Referenzen keinen belastbaren Änderungsrang: Sie werden defensiv
als ungeklärt behandelt, niemals als neueste Änderung. Ein älteres Add kann
keinen neueren Remove-Tombstone rückgängig machen. Eine Namensänderung ist keine
Versandfreigabe; Entfernen löscht weder Verlauf noch Ticket.

## Wiederverwendeter Bestand und dauerhafte Kette

Wiederverwendet werden verschlüsselte Verbindungen, geprüfte Nummern-/Kontobindung,
Versions-CAS, Zugangsresolver, `atomic_database`, Kommunikationssperre,
`whatsapp_messages`, `whatsapp_events`, Versandfinalisierung/Recovery und der
geschützte Bildabruf. Es gibt keine zweite Tokenkonfiguration, Nachrichtenablage
oder Queue-Plattform.

Neu sind kleine Metadatentabellen `whatsapp_sync`, `whatsapp_sync_teile` und
`whatsapp_kontakte`. Der bestätigte Signup/Abonnementabschluss legt beide
Sync-Aufträge atomar für genau diese Verbindungsversion an. Das vorhandene
Anschlussdashboard startet die getrennten Anforderungen ausdrücklich und kann
nach Browser-/Prozessneustart mit einer **aktuellen** berechtigten Sitzung
fortsetzen; die alte Signup-Sitzung ist dafür nicht nötig.

Eine einmalige Operation wechselt vor HTTP dauerhaft von `offen` zu `reserviert`.
Parallele Aufrufe werden unter denselben Datenbanksperren abgeglichen. HTTP läuft
ohne gehaltene Datenbanktransaktion. Timeout bleibt `unklar`; ein Prozessabbruch
direkt nach Reservierung bleibt sichtbar reserviert und darf ebenfalls nicht
nochmals starten. Es gibt keine automatische Wiederholung externer Starts.
Erneute Dashboard-Aktionen können noch nicht gestartete Schritte und die lokale
Journalverarbeitung fortsetzen. Späte Antworten ergänzen gegebenenfalls die
Request-ID, setzen aber gelieferten Fortschritt, Abschluss oder Ablehnung nicht
zurück. Widersprüchliche Ablehnung nach Datenlieferung bleibt prüfpflichtig.

Der HMAC-/Field-Dispatcher validiert verschachtelte Importdaten vor Wirkungen
und verarbeitet Kontoereignisse in gemischten Paketen zuerst. Bereinigte
Lieferungen werden im bestehenden Ereignisjournal dauerhaft erfasst. Die
anschließende lokale Hintergrundverarbeitung und ihr Erledigungsvermerk sind
transaktional. Nach einem Prozessabbruch setzt die Dashboard-Status-/Fortsetzen-
Aktion offene Einträge fort. Nach Import bleibt im Journal nur die deduplizierende
Kennung mit Versionsbezug; Nachrichtentexte werden dort nicht nochmals behalten.
Vorauseilende Medien besitzen vorübergehend nur einen begrenzten Metadateneintrag.

Begründete Grenzen: höchstens **4 MiB** Webhook-Body, **5.000** Importdatensätze
pro Lieferung, **100** Änderungen sowie begrenzte Texte, IDs und verschachtelte
Listen. Reine Live-Lieferungen behalten zusätzlich 256 KiB und 100 Ereignisse.
Die Providerdokumentation erlaubt große Import-Batches; darüber hinausgehende
Pakete werden ausdrücklich abgewiesen, nicht unbeschränkt aufgenommen. Der
lokale Hintergrundlauf verarbeitet höchstens 100 Journal-Lieferungen pro Aufruf.
Das ist kein Lastnachweis für sämtliche möglichen realen Importgrößen.

## Generationserkennung und Widerruf

Jeder Auftrag, Transportversuch, Journalbezug und Chunk enthält Werkstatt,
WABA, Nummer und verifizierte lokale Version. Capture, Import und HTTP-Abschluss
prüfen die aktuelle autorisierte Verbindung; die Datenbank-Sperre ordnet einen
konkurrierenden Widerruf vor oder nach dem jeweiligen lokalen Commit.

Die gelesenen History-/Kontakt-Payloads spiegeln weder `request_id` noch unsere
Version wider. Daher ist eine neue lokale Version allein **kein** Generationsbeweis.
Die erste lokal vollständig beobachtete Initialisierung darf nur nach der
Reservierung ihrer einzigen bekannten Generation aufnehmen. Für bereits bekannte
WABA-/Nummer-Paare mit früherem Auftrag sperrt ein Neuanschluss die automatische
Zuordnung als `pruefung`; alte Chunks/Kontakte werden nicht in die neue Generation
importiert. Migrierte Anschlüsse ohne initialen Nachweis bleiben ebenfalls offen
zur Prüfung. Es gibt keine öffentliche Aktion, die diesen Schutz übergeht.

**Protokollgrenze:** Auch die erste lokal beobachtete Generation beweist nicht,
dass Meta außerhalb dieses lokalen Bestands niemals einen früheren Lauf hatte.
Nicht lokal bekannte alte Lieferungen desselben Kontos lassen sich mit den
dokumentierten Feldern nicht mathematisch unterscheiden. Die Freigabe einer
späteren realen Installation muss diesen Ausgangsbestand und die tatsächlichen
Providerlieferungen prüfen. Wiederanschluss wird hier konservativ nicht als
automatisch synchronisierbar ausgegeben. Bereits gestartetes HTTP lässt sich
bei anschließendem Widerruf nicht zurückrufen, sein spätes Ergebnis aber lokal
nicht mehr bestätigen.

## Historie, Kontakte und Oberfläche

Historische Nachrichten erhalten `source=whatsapp_historie`, ursprüngliche Zeit
und Importbezug im vorhandenen Datensatz. Die bestehende chronologische Anzeige
kennzeichnet sie als importiert. Richtung und Teilnehmer werden gegen die konkrete
Geschäftsnummer geprüft. Ohne sichere Zuordnung bleibt eine Lieferung prüfpflichtig;
es wird kein aktuelles Ticket angeheftet.
Bei neu importierten ausgehenden Nachrichten wird der belegte historische
Zustellstatus übernommen; ohne diesen Nachweis bleibt er unbekannt. Der heutige
Standardwert „gesendet“ wird dafür nicht erfunden. Eine gesonderte Regression
prüft ursprüngliche Chronologie, historischen Fehler und fehlenden Status.

Import ruft weder Chatverarbeitung noch Intake, Ticketanlage, Zuständigkeitswechsel,
Antwortreservierung oder Sendung auf. `message_timestamp=None` verhindert den
Inbound-Standardzeitpunkt; auch nach erneuter Migration öffnet kein Import das
API-Servicefenster. Bereits bekannte Live-/Echo-Datensätze behalten Status,
Kontrollrevision, Ticketverknüpfung und Recovery-Unsicherheit. Eine mögliche eigene
Sendung ohne Provider-ID bleibt zur Prüfung offen; erst belegte Identität darf
die gemeinsame Finalisierung zusammenführen. Die beiden unabhängigen Aufgabe-3-
Gegenproben bleiben im Methodenrumpf unverändert.

Medienplatzhalter und Nachlieferung werden anhand derselben Provider-ID verbunden.
Bilder verwenden den bestehenden geschützten Abruf; alte Importversionen bekommen
keinen Bildabruf mit einer neuen Verbindung. Andere Medientypen und fehlende
Inhalte bleiben kenntlich, ohne neue OCR, Transkription oder Dateikopie.
Importierte Kontakte sind im werkstattgebundenen Datenschutzexport und in der
bestehenden ausdrücklichen Kundendatenlöschung berücksichtigt.

Technische Bereitschaft verlangt einen aktuellen autorisierten Anschluss ohne
Konto-/Generationskonflikt, einen angenommenen Kontaktauftrag ohne Kontaktkonflikt
sowie abgeschlossene, nachweislich nicht geteilte oder lokal ausdrücklich
ausgelassene Historie. Das bedeutet **nicht** vollständige Kontakte oder verfügbare
Medien. Betriebliche Bereitschaft bleibt separat und geschlossen. Eine isolierte
`coexistence_bereit=1`-Flagge umgeht fehlende/alte Sync-Nachweise nicht. M1-Legacy
wird nicht an diese Coexistence-Bedingung gebunden; einmal zurückgehaltene Eingänge
bleiben auch nach späterer Bereitschaft und Wiederzustellung ausgeschlossen.

## Prüfnachweise

Abschließender Stand vom 29. Oktober, nach allen beschriebenen Korrekturen:

- **719/719 Python-Tests bestanden**, **362,645 Sekunden**, keine übersprungenen
  Tests. Python **3.12.13**, SQLite **3.46.1**, PostgreSQL **18.6**, psycopg **3.2.3**.
  Darin **69 tatsächlich ausgeführte PostgreSQL-Tests** auf einer eigenen neu
  angelegten leeren Wegwerfdatenbank. Die übrigen Tests laufen überwiegend auf
  SQLite; dies ist keine vollständige Anwendungssuite ausschließlich auf PostgreSQL.
- Neu enthalten sind **34 Sync-Fälle auf jeder Datenbank** und eine zusätzliche
  HTTP-Integration vom verifizierten Signup bis zur Synchronisierung nach Ablauf
  der alten Signup-Sitzung. CAS/Parallelität, Prozessneustart, Widerruf, Migration,
  Medien, Chunk-Konflikte, Kontakte, Isolation, Servicefenster und beide bisherigen
  Echo-Gegenproben wurden tatsächlich geprüft. Events/Barrieren statt Zufallssleeps.
- **62/62 JavaScript-Tests bestanden**, Node.js **24.16.0**, keine Auslassungen.
  Darunter vier neue Sync-Oberflächenfälle. Separater echter Chrome-Nachweis siehe unten.
- AST-Vergleich bestätigt: die gesamte Datei der Aufgabe-3-Gegenproben bleibt
  gegenüber `326f000` unverändert. Die ergänzte gemeinsame Versand-Fixture ersetzt
  keine Assertion dieser Gegenproben.
- Diff-/Whitespace- und Geheimnisprüfung ohne Befund. Eigene Prüfcontainer und
  Prüfnetz entfernt: `postgres_bereinigung.json` bestätigt beide Schritte;
  anschließender Docker-Abgleich findet keine entsprechenden Ressourcen, auch
  keine gestoppten Container.

Die vollständige Suite verwendet einen HTTP-sperrenden Starter und bindet nur
Quellen, Tests, Templates, Rechtstexte, Abhängigkeiten und den Prüfstarter lesend
in den Testcontainer ein. Keine `.env`, Kundendaten oder alten Protokolle.
Die folgenden gezielten Gruppen und Vorläufe überlappen und werden nicht addiert.

Vorprüfungen: 26 neue SQLite-Fälle bestanden nach Fixture-Korrektur. Die erste
Sync-Fixture hatte einen vor App-Start erzeugten Altanschluss fälschlich als
frischen Signup behandelt; die Migration sperrte ihn zutreffend (23 Fehler und
ein nachfolgender Fehler im 26er-Lauf). Die Fixture erzeugt jetzt ausdrücklich
einen synthetischen frischen Auftragsnachweis. Ein diagnostischer Einzellauf
bestätigte zuvor die Ursache; kein automatischer Retry.

Die ersten bestehenden Regressionen zeigten acht Fehlschläge und einen Fehler
in 46 Fällen: bisherige Versand-Fixtures setzten nur die Betriebsflagge, und alte
Feldtrennungs-Fixtures verwendeten keinen dokumentierten History-Aufbau. Die
Fixtures wurden um technische Nachweise bzw. gültige Payload-Strukturen ergänzt,
nicht die Schutzbedingungen gelockert. Danach bestanden 68 gezielte Anschluss-/
Echo-/Korrekturregressionen. Die beiden ursprünglichen Gegenproben wurden nicht
inhaltlich verändert.

Eine Vorprüfung mit frischem PostgreSQL führte 123 Fälle aus; zwei neue
API-/History-Korrelationsfälle scheiterten am Vergleich einer virtuellen mit
einer erstmals angelegten Gesprächskontrolle. Die Versand-Fixture legt jetzt,
wie die echte Reservierung, vorher ihre Kontrolle an. Die strenge Assertion
bleibt erhalten. Prüfcontainer und Netz dieses Vorlaufs wurden entfernt.

Der erste vollständige Lauf führte 714 Tests aus und hatte einen Fehlschlag:
ein bestehender UI-Vertrag erwartet im Sperrhinweis das Wort „gesperrt“.
Die neue Formulierung verwendete „geschlossen“. Der Produkttext wurde auf die
bestehende klare Sperrformulierung angepasst; die Assertion blieb unverändert.
Zusätzlich wurde beim abschließenden Review die HTTP-Annahmevalidierung gegen
widersprüchliche Antworten mit gleichzeitiger Request-ID und Fehlerobjekt
gehärtet und auf beiden Datenbanken abgesichert. Deshalb folgt ein neuer
vollständiger Lauf, keine automatische Wiederholung zur Fehlermaskierung.
Die abschließende Codeprüfung ergänzte außerdem die oben beschriebene explizite
Statusabbildung neuer historischer Ausgänge. Der abschließende Vollnachweis muss
auch diese Änderung und ihre zusätzliche Chronologie-/Statusregression enthalten.

Der folgende 716er-Lauf hatte einen Fehlschlag im PostgreSQL-Duplikatfall:
technische Bereitschaft war unerwartet falsch. Die Prüfung der Fixture zeigte,
dass sie für die vermeintliche Wiederholung den Payload samt aktueller Sekunde
neu erzeugte. Eine Sekundengrenze macht daraus eine widersprüchliche Wiederholung,
die fachlich gesperrt bleiben muss. Die Fixture verwendet jetzt exakt denselben
Payload für beide Zustellungen; die Bereitschaftsassertion bleibt erhalten und
zeigt bei Abweichung den bereinigten Status. Ein bereits gestarteter weiterer
Containerlauf wurde noch vor Ausgabe von Python-Testfällen beendet, damit diese
Korrektur nicht durch zufällige Wiederholung verdeckt wird. Seine Bereinigung ist
ebenfalls belegt. Der abschließende Lauf erfolgt danach mit unveränderten Fixtures.

Browsernachweis: tatsächliches Anschluss-Template mit tatsächlichem CSP,
Chrome **156.0.8078.73**, fünf Zustände (offen, laufend, abgeschlossen, nicht geteilt,
prüfpflichtig), Statusaktion und Mobilbreite 390 Pixel. Alle Browseranfragen
wurden abgefangen; Desktop- und Mobilbilder wurden visuell kontrolliert.
Auch der tatsächlich gerenderte Posteingang wurde in Chrome geprüft: importierte
Herkunft und fehlende Medien sind sichtbar; der Verlaufsausschnitt wurde visuell
kontrolliert. Die Browserprüfung importiert keine realen Medien.
Meta-SDK-Netzwerk war absichtlich gesperrt: dies ist eine Prüfung der neuen
Sync-Oberfläche, kein erneuter Signup-/SDK-Vertragsnachweis.

Lokale Starter, Protokolle, Browserbilder, öffentliche Dokumentationskopien und
Prüfpakete liegen ausschließlich unter `artifacts/m2-synchronisierung/`, außerhalb
von Git und Docker-Images. Test-HTTP ist gesperrt, nur ausdrückliche Simulationen
sind zugelassen. Kein echter Meta-Anschluss, kein Kundentoken, keine Kundennummer,
Produktionsdatenbank, Kontoeinstellung oder reale Sendung wurde verwendet.
Keine vollständige Coexistence-Freigabe, kein Merge/Deployment, kein Beginn von Aufgabe 5.

## Nächster Schritt

Unabhängige Prüfung von Aufgabe 4.
