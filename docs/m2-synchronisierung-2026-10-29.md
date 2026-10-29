# M2, Aufgabe 4: Historie, Kontakte und sichere Synchronisierung

Stand: 29. Oktober 2026. Die unabhängige Prüfung von `ee4127f` hat zwei P2-Fehler
nachgewiesen; Aufgabe 4 ist noch nicht abgenommen. Beide Ursachen sind lokal
korrigiert. Die unabhängige Nachprüfung der Korrekturen und der reale Meta-Nachweis
stehen aus. `coexistence_bereit` bleibt 0. Keine Betriebsfreigabe.

## Zwei enge Korrekturen nach dem unabhängigen Review

Korrekturbasis: `ee4127fa4a652772b305ec38f6ecb6c2155de47e`, vor Änderungen lokal
und remote identisch, Arbeitsbaum sauber. Eigene Aufgabenbranch:
`codex/m2-synchronisierung-korrekturen-2026-10-29`.
Gelesen wurden der unabhängige `PRUEFBERICHT.txt` und `gegenproben.py` unter
`C:\Users\Mikolaj\Documents\New project\m2-synchronisierung-review-2026-10-29\`.
Die dort bestandenen **719 Python-Tests (69 PostgreSQL)** und **62 JavaScript-Tests**
sind historische Reviewnachweise. Drei zusätzliche Gegenproben scheiterten dort
auf beiden Datenbanken. Aufgaben 1–3 einschließlich der Echo-Korrekturen bleiben
die vorhandene Grundlage; daraus folgt keine Abnahme von Aufgabe 4.

**P2-1, bekannte offene Importarbeit:** `erfasse` speicherte `sync_offen` dauerhaft,
doch `technisch_bereit` prüfte nur die bereits verarbeiteten Auftragszustände.
Dadurch konnten Status, normaler Eingang und automatische Versandprüfung vor
dem Hintergrundlauf noch Bereitschaft sehen. Jetzt gehört das Fehlen aktueller
offener Journaleinträge zur technischen Bereitschaft. Werkstatt, Nummer und
Versionspräfix werden abgegrenzt; dieselbe Version ist über die zuvor geprüften
Aufträge an die aktuelle WABA und Nummer gebunden. Capture und Erledigung stehen
unter derselben Kommunikationssperre wie Eingang und letzte Versandprüfung.
Der bestehende Journaleintrag ist selbst die atomare Sperre, ohne zusätzliche
Flagge, Tabelle, Migration oder zweite Queue.

Erledigte identische Lieferungen werden durch den bestehenden eindeutigen
Ereignisschlüssel nicht wieder offen. Unverarbeitete Duplikate, Abschlussmeldungen
und Neustarts beseitigen aktuelle Arbeit nicht. Nach atomarem Import und
Erledigungsvermerk gilt wieder der fachliche Auftragszustand: vollständige
widerspruchsfreie Historie kann bereit sein, Lücken und Konflikte bleiben gesperrt.
Einträge einer alten Version sperren kein anderes verifiziertes Nummern-/Kontopaar
und werden bei Recovery ohne Import erledigt. Der bestehende strengere Schutz
für nicht unterscheidbare Wiederanschlüsse desselben Paares bleibt erhalten.
Einmal zurückgehaltene Live-Eingänge werden auch nach späterer Bereitschaft nicht
nachverarbeitet; abgebrochene reservierte Antworten werden nicht erneut gesendet.

**P2-2, Lieferung bei 0 Prozent:** Die alte Bedingung `not fortschritt` deutete
bereits importierte Daten fälschlich als fehlende Lieferung und erlaubte danach
`nicht_geteilt`. Jetzt werden die gespeicherten Teile derselben Werkstatt/Version
und der dauerhafte History-Verarbeitungszustand berücksichtigt. `laufend` und
`abgeschlossen` entstehen atomar mit der Verarbeitung, auch bei Medien vor einem
Thread oder Medien zu einer schon bekannten Nachricht. Deshalb bleiben diese
Nachweise nach Neustart erhalten, selbst wenn kein Medien-Journaleintrag mehr
existiert und der Prozentwert 0 ist. Eine spätere Ablehnung führt zu `pruefung`,
ohne Nachrichten zu löschen oder normale Kundenannahme auszulösen.

Auch eine früher akzeptierte leere Lieferung wird vorsichtshalber als Widerspruch
behandelt; sie beweist nicht, dass keine Lieferung stattfand. Eine tatsächlich
erstmalige Ablehnung ohne vorherige Lieferung sowie deren identische Wiederholung
bleiben zulässig. Daten und Ablehnung innerhalb desselben `value` weist der
bestehende Parser in beiden Reihenfolgen vor Wirkungen ab; getrennte `changes`
im selben signierten Paket führen in beiden Reihenfolgen zu `pruefung`.
Es wurden keine Providerfelder, neue Providerannahmen oder externen Ereignisse
eingeführt; die Korrektur betrifft ausschließlich lokale Nachweise und Sperren.
Ein erneuter Dokumentationsabruf war dafür nicht erforderlich.

Wiederverwendet bleiben `atomic_database`, Kommunikationssperre, Versionsbindung,
Journal-Deduplizierung, Kontrollrevisionen, Dispatch-Reservierung, Finalisierung
und Recovery. Die verbindlichen Eingangs- und Versandprüfungen nutzen bereits
`automatik_gesperrt` und damit die korrigierte Bereitschaft; dort war keine weitere
Produktänderung nötig. Oberfläche und Signup bleiben unverändert.

## Neue Prüfungen der beiden Korrekturen vom 29. Oktober

Die drei Originalmethoden wurden auf der unveränderten Basis zuerst namentlich
geladen: **SQLite 3/3 erwartete Assertion-Fehlschläge**, **PostgreSQL 3/3 erwartete
Assertion-Fehlschläge**, keine Fixture-/Importfehler oder Auslassungen. Die externe
Datei ist unverändert; ihre lokale Prüfkopie ist bytegleich. AST-Vergleich bestätigt
unveränderte Methodenrümpfe und Assertions in der dauerhaften Regression.
Die neue Testklasse übernimmt nur Fixture-Helfer, keine geerbten Bestandsfälle.

Nach der Korrektur bestanden die Originale getrennt: **3/3 SQLite** unter Python
**3.14.3**, SQLite **3.50.4**, sowie **3/3 PostgreSQL** unter Python **3.12.13**.
Der gezielte Containerlauf bestand mit **39/39 Fällen in 49,696 Sekunden**:
18 neue SQLite-Regressionsfälle, dieselben 18 auf PostgreSQL sowie die drei extern
geladenen PostgreSQL-Originale. Diese Gruppen überlappen fachlich und werden
nicht zur Gesamtsuite addiert. Ein früherer lokaler Entwicklungslauf mit 17 noch
nicht vollständig ergänzten SQLite-Fällen war ebenfalls erfolgreich.

Zusätzliche Regressionen prüfen Capture-Rollback, Halt vor Hintergrundlauf,
Neustart in einem frischen Prozess, Abschluss/Lücken und Duplikate, Kontaktarbeit,
zwei Werkstätten, neue Versionen, Medien bei 0 Prozent, echte erste Ablehnung
und gemischte Lieferungen. Deterministische Events ordnen Capture gegen normalen
Eingang sowie Capture nach Dispatch-Reservierung vor der letzten lokalen
Versandprüfung; keine Zufallssleeps oder automatischen Test-Retries.

Vollständiger Abschlusslauf: **755/755 Python-Tests in 448,350 Sekunden bestanden**,
darin **87 tatsächlich ausgeführte PostgreSQL-Fälle** und **668 SQLite-/datenbank-
unabhängige Fälle**. Keine Fehler, Fehlschläge oder Auslassungen. Python **3.12.13**,
SQLite **3.46.1**, PostgreSQL **18.6**, psycopg **3.2.3**. Der Lauf verwendet eine
erneut eigens angelegte leere PostgreSQL-Wegwerfdatenbank und gesperrten echten
HTTP-Transport. Das ist keine vollständige Anwendungssuite nur auf PostgreSQL.
**62/62 JavaScript-Tests bestanden**, Node.js **24.16.0**, ebenfalls ohne Auslassungen.
Nach der Produktkorrektur gab es keine fehlgeschlagenen Testvorläufe; die sechs
erwarteten Baseline-Fehlschläge sind oben getrennt ausgewiesen. Eine absichtlich
simulierte Ausnahme im bestehenden Zuverlässigkeitstest erscheint im Vollprotokoll,
ist aber kein fehlgeschlagener Test. Keine automatischen Wiederholungen.

Die komplette Datei `tests/test_whatsapp_echo_korrekturen.py` bleibt gegenüber
der Basis unverändert. Diff-/Whitespace-Prüfung und begrenzter Geheimnisscan über
alle vier geänderten/neuen Dateien ohne Befund; kein vollständiger Sicherheitsaudit.
Alle eigenen Prüfcontainer und Netze der Baseline-, gezielten und vollständigen
PostgreSQL-Läufe wurden im jeweiligen `finally` entfernt. Die separaten
Bereinigungsnachweise und der anschließende Docker-Abgleich bestätigen: keine
zugehörigen Container (auch keine gestoppten) oder Netze verbleiben.

Grenzen: Diese lokalen Prüfungen sind keine unabhängige Abnahme und kein realer
Meta-, Last- oder Produktionsnachweis. Kein neuer Browserlauf für die unveränderte
Oberfläche; der unten dokumentierte Chrome-Lauf bleibt ein historischer Nachweis.
Keine globale Exactly-once-Zusage: ein bereits begonnener externer HTTP-Aufruf
ist nicht rückholbar, die Sperre gilt am bestehenden letzten lokalen Übergabepunkt.
Provider-Generationen ohne unterscheidbare Kennung, fehlender globaler
Kontaktabschluss und nicht verfügbare Medien bleiben die bestehenden Grenzen.
Keine echten Konten, Kundendaten, Meta-Konfiguration, Merge, Deployment oder
Aufgabe 5. Lokale Artefakte liegen ausschließlich im ignorierten Verzeichnis
`artifacts/m2-synchronisierung-korrekturen/`, außerhalb von Git und Docker-Images.

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

## Historische Prüfnachweise der Erstimplementierung

Damals abschließender Stand vom 29. Oktober vor dem unabhängigen Review;
keine Prüfergebnisse der oben beschriebenen beiden P2-Korrekturen:

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

Unabhängige Nachprüfung dieser beiden Korrekturen von Aufgabe 4.
