# M2: lokale Gesamtabnahme vom 29. Oktober 2026

## Urteil und geprüfter Stand

**Lokale M2-Gesamtabnahme bestanden.** Die integrierte Kette mit zwei künstlichen
Werkstätten besteht auf SQLite und PostgreSQL. Der einmalige vollständige
Abschlusslauf besteht mit **761/761 Python-Tests**, darunter **90 PostgreSQL**,
ohne Fehler oder Auslassungen. Die lokale Browserkontrolle und **62/62
JavaScript-Tests** bestehen ebenfalls. **Reale Coexistence ist nicht geprüft**;
die Produktflagge `coexistence_bereit=0` bleibt unverändert.

Geprüfter Produktcode: **`1eca6c15d0b1aca020ef2cdcaa22d95c2010a5a6`**.
Zu Beginn waren lokales HEAD und Remote der Korrekturbranch identisch und der
Arbeitsbaum sauber. Abnahmebranch: `codex/m2-lokale-abnahme-2026-10-29`.
App-Code, Migrationen, Produktkonfiguration, Oberfläche und bestehende Tests
wurden nicht verändert. Ergänzt werden dieser Bericht, der Projektstand und zwei
reproduzierbare Testquellen. Kein Merge, Deployment oder Kundenbetrieb.

Gelesen wurden `AGENTS.md`, Projektstand und die Berichte zum
[Verbindungsmodell](m2-verbindungsmodell-2026-10-27.md),
[Embedded Signup](m2-embedded-signup-2026-10-27.md),
[Business-App-Ereignissen](m2-business-app-ereignisse-2026-10-28.md) und zur
[Synchronisierung](m2-synchronisierung-2026-10-29.md). Maßgeblich für die inzwischen
erfolgte Nachprüfung ist außerdem der externe Bericht unter
`C:\Users\Mikolaj\Documents\New project\m2-synchronisierung-korrektur-review-2026-10-29\PRUEFBERICHT.txt`.
Er nimmt beide P2-Korrekturen lokal an; die frühere Aufforderung zur Nachprüfung
in der Produktdokumentation ist damit erledigt.

**Historische Wahrheit:** Der letzte unabhängige Vollverlauf erreichte
**753/755**, mit einem `ConnectionTimeout` im PostgreSQL-Setup und einer generischen
HTTP-400-Antwort während einer langen Unterbrechung des Ausführungsumfelds.
Die innere Ursache der 400-Antwort wurde damals nicht protokolliert. Genau diese
beiden unveränderten Fälle bestanden anschließend auf frischem PostgreSQL **2/2**.
Das wird nicht in einen grünen 755er-Einzellauf umgedeutet. Die früheren 755/755
des Implementierers und die früheren Gegenproben sind ebenfalls keine Ergebnisse
dieser Gesamtabnahme.

## Aufbau und Abgrenzung

`tests/test_m2_gesamtabnahme.py` verwendet die vorhandene isolierte
Verbindungs-Fixture, `MetaSimulation`, echte Sitzungsprüfung und echte HTTP-Routen.
Jeder Test legt zwei eigene synthetische Werkstätten mit getrennten Benutzern,
Sitzungen, WABAs, Nummern und Testzugängen an. Absichtlich ist die Kundennummer in
beiden Werkstätten gleich: der Gesprächsbezug muss trotzdem getrennt bleiben.
Bootstrap schreibt nur Werkstätten/Benutzer/Abostatus, keine erfolgreiche
Verbindung. Der tatsächliche Signup-Dienst prüft Code, App, Rechte, Ressourcen,
Abonnement und Versionswechsel und schreibt selbst die Autorisierung.

Nur die bestehende HTTP-Grenze wird simuliert. Unbekannte Hosts, Pfade und Zugänge
scheitern. Auch beim simulierten Transport wird die Abwesenheit einer gehaltenen
Datenbanktransaktion geprüft. Der Medienabruf durchläuft Resolver, Metadaten- und
Binärabruf; sein künstliches PNG-Prüfpräfix ist kein echtes Kundenfoto oder
Bilddecoder-Nachweis. Die Prüfuhr liegt beim Signup 60 Sekunden früher und bei
einer bewussten Freigabe zehn Sekunden früher, damit die fachlich verschiedenen
Zeitpunkte ohne Zufallssleeps eindeutig geordnet sind. Keine Anschlusszeit oder
Autorisierung wird dafür direkt in einer Produktzeile umgeschrieben.

**Phase 1 bleibt produktgetreu:** Nach bestätigtem Signup und technischer
Synchronisierung ist `coexistence_bereit=0`. Normale Eingänge werden dauerhaft
zurückgehalten. Keine Kundenannahme, kein Ticket, kein heutiges Servicefenster
und keine automatische Sendung durch Historie oder zurückgehaltene Nachrichten.

**Phase 2 ist ausschließlich künstlich:** Erst nach diesen Assertions setzt
`freigabe_nur_im_fixture` die Flagge in den beiden isolierten Prüfwerkstätten
auf 1. Danach werden zuvor zurückgehaltene Kennungen erneut zugestellt und
bleiben ausgeschlossen. Erst neue Kennungen prüfen den späteren Automatikpfad.
Diese direkte Fixture-Aktion ist keine heute vorhandene Freigaberoute und keine
betriebliche oder Meta-Freigabe. Produktdateien behalten unverändert ihren Schutz.

## Phasen und tatsächliche Nachweise

Die neue Kette lief auf SQLite und einer eigenen, vor Start nachweislich leeren
PostgreSQL-Datenbank. Die drei Methoden werden je Datenbank einmal geladen;
keine zusätzlich geerbten Bestandstests werden als neue Integrationsfälle gezählt.

| Phase | Lokaler HTTP-/Datenbankstatus | Erwartung und beobachteter Nachweis | Grenze |
| --- | --- | --- | --- |
| Anschluss zweier Werkstätten | Bestanden | `/verbinden/start` und `/abschluss`: genau ein Codeaustausch, serverseitige App-/Rechte-/Nummernprüfung, bestätigtes Kontoabonnement, Version 2 und getrennte auflösbare Zugänge. Wiederholung des Abschlusses wird abgelehnt. | Simuliertes Meta; Browser-SUCCESS ist kein Nachweis. |
| Synchronisierung | Bestanden | Zwei einmalige Anforderungen; signierter Import dauerhaft erfasst, Bereitschaft vor Hintergrundlauf falsch; eigener neuer Python-Prozess verarbeitet das Journal. Identische Wiederholung erzeugt keine zweite Nachricht. Medien kommen getrennt, Kontakte werden werkstattgebunden übernommen. | Kein globaler Kontaktabschluss und kein vollständiger Medienbestand zugesagt. |
| 0 Prozent und Ablehnung | Bestanden | Nach echtem Signup führt importierte Nachricht bei 0 Prozent und spätere Ablehnung zu `pruefung`; Nachricht bleibt erhalten. Im anderen Konto ist erste Ablehnung ohne vorherige Daten zulässig. | Konservativer Widerspruchsschutz, kein neuer Providervertrag. |
| Produktzustand | Bestanden | Beide technisch bereiten Anschlüsse bleiben bei Flagge 0 gesperrt. Keine Sendung; wiederholte zurückgehaltene Kennung bleibt auch nach künstlicher Freigabe ausgeschlossen. | Keine produktive Freigabefunktion geprüft oder ergänzt. |
| Künstlich freigegebener Intake | Bestanden | Vier neue Texte je Werkstatt durchlaufen die reale Kundenannahme. Genau ein Ticket mit verifiziertem Absender und aktiver Gesprächsverknüpfung; je Eingang genau eine vorgesehene simulierte Sendung. Wiederzustellung sendet nicht erneut. | Zustellung wird simuliert, keine echte Kundennachricht. |
| Dashboard und Telefon getrennt | Bestanden | Manuelle Antwort über `/dashboard/whatsapp/reply`, gleicher Versuch zweimal: nur eine Sendung. Nach bewusstem Fortsetzen übernimmt ein neues Telefon-Echo einmalig; offene Kundenfrage und Reparaturstatus bleiben erhalten. Neuer Eingang im manuellen Zustand sendet nicht automatisch. | Tatsächliche Business-App und Telefon nicht beteiligt. |
| Eigene/verspätete Rückmeldungen | Bestanden | Eigene Provider-ID verknüpft Echo ohne Übernahme. Frühes `read` und Echo während simuliertem HTTP werden bei Finalisierung in genau einen Ausgang gefaltet. Duplikat und erstmals verspätetes altes Echo ändern bewusstes Fortsetzen nicht. | Gleichsekündigkeit bleibt laut unveränderter Regression prüfpflichtig; keine globale Reihenfolge. |
| Offboarding und Isolation | Bestanden | Signiertes Offboarding sperrt A: kein Resolverzugang, kein neuer Versand, Medien HTTP 409, keine Wiederautorisierung durch `ACCOUNT_RECONNECTED`. Unabhängiges B behält Zugang, Kontrolle und Medienabruf. | Bereits begonnenes externes HTTP lässt sich nicht zurückrufen. |
| Fremdzugriff und ungültige Herkunft | Bestanden | B darf A weder verbinden noch synchronisieren oder dessen Bild abrufen. Posteingang/Kontrollroute erzwingen die Sitzungswerkstatt statt des manipulierten Parameters; A bleibt unverändert. Falscher Origin, fehlende/manipulierte HMAC, falsches Konto, Rollenverlust und fehlende Sitzung sperren. | HTTP 200 im eigenen Posteingang wurde ausdrücklich nicht mit Zugriff auf A verwechselt. |

Neue Methoden (je SQLite und PostgreSQL):

- `test_zwei_werkstaetten_vom_signup_bis_zum_offboarding`
- `test_fremdzugriff_und_signatur_ueber_die_integrierten_routen`
- `test_null_prozent_ablehnung_und_fruehe_rueckmeldung_nach_signup`

## Wiederverwendete negative und konkurrierende Belege

Die unveränderten Originalgegenproben aus dem externen `gegenproben.py` wurden
namentlich geladen: **3/3 SQLite und 3/3 PostgreSQL bestanden**. Die externe Datei
bleibt unverändert. Die bestehenden Echo- und Sync-Korrekturdateien behalten
sämtliche Assertions und ihren gesamten Inhalt gegenüber dem geprüften SHA.
SHA-256 der unveränderten externen Datei:
`283d313c406e83c7cedc5678ede8e621be226f6d4786404d1a6c4ca9ee378c34`.

Der gezielte Lauf wiederholt zusätzlich Anschluss-, Ereignis-, Echo- und
Sync-Korrekturregressionen. Der vollständige Lauf umfasst auch die übrigen
Verbindungs-, Synchronisierungs-, Versand-/Recovery-, Medien- und Auth-Tests.
Besonders maßgeblich sind:

- `test_capture_transaktion_ordnet_parallelen_normalen_eingang` und
  `test_capture_nach_dispatch_reservierung_stoppt_letzte_versandpruefung`:
  Erfassung offener Arbeit gegen normalen Eingang beziehungsweise die letzte
  lokale Prüfung einer bereits reservierten Antwort; danach kein Nachversand.
- `test_neustart_sperrt_vor_recovery_und_wiederholt_keinen_eingang`,
  `test_duplikate_abschluss_und_luecke_loesen_nur_passende_sperre` und
  `test_alte_version_gibt_neue_weder_frei_noch_dauerhaft_gesperrt`:
  Journal, Lücken, Duplikate, Neustart und Generationsabgrenzung.
- Anschluss-Abbruch vor/nach dauerhaftem Abschluss, Rollen-/Sitzungsentzug
  während HTTP, eindeutige Nummernreservierung und Versions-CAS gegen Widerruf.
- Echo gegen vorbereitete/reservierte Antwort, parallele identische Echos,
  laufender Import gegen Widerruf und Kontoereignis gegen neue Verbindungsversion.
  Diese relevanten Konkurrenzmethoden laufen auf beiden Datenbanken mit
  vorhandenen Events/Haltepunkten; keine zufälligen Sleeps oder Test-Retries.
- Kontoweiter Widerruf mehrerer Nummern derselben WABA und Schutz eines fremden
  Kontos; alte Rückmeldung darf eine neue Version nicht überschreiben.
- Timeout und unklarer Ausgang einmaliger Initialisierung/Sendung,
  `sending/unknown`, Recovery ohne Provider-ID und späte eindeutige Identität:
  keine blinde neue Sendung. Begrenzte M1-Legacy-Zuordnung bleibt erhalten.

Vorhandene Datenbanktransaktionen, Kommunikationssperren, Kontrollrevisionen,
verschlüsselte Verbindungen, Nachrichtenbestand, Journal, Dispatch-Reservierungen
und Recovery werden ohne Ersatzimplementierung geprüft. Diese lokalen Tests
beweisen keine verteilte Exactly-once-Eigenschaft.

## Browsernachweis, gesondert von Datenbank und Meta

**Bestanden für die geprüften lokalen Ansichten:** Chrome **156.0.8078.73**,
29. Oktober 2026, Desktop **1200 px** und Mobil **390 px**. Die neue Quelle
`tests/m2_browser_abnahme.cjs` erzeugt ihre Seiten durch die oben geprüfte reale
HTTP-/Datenbankkette. Gerendert werden tatsächliche Templates mit ihren tatsächlichen
CSP-Headern/Nonces, keine nachgebaute Oberfläche. Neun Ansichten je Breite:
offen, laufend, abgeschlossen, nicht geteilt, prüfpflichtig, widerrufen,
Einstellungen mit bestätigter/widerrufener Autorisierung sowie Telefonverlauf.
DOM-Prüfungen bestätigen Status, historische Kennzeichnung, Telefonantwort,
manuelle Zuständigkeit und fehlenden horizontalen Überlauf. Die Sync-Statusaktion
läuft mit unverändertem Origin/CSP und kontrollierter Antwort.

Screenshots wurden für Mobil-Syncfehler und Desktop-/Mobil-Telefonverlauf visuell
kontrolliert; zusätzlich wurden Ausschnitte nach Scrollen zur Telefonantwort
gesichert und auf beiden Breiten visuell kontrolliert. Keine UI-Umgestaltung
oder Lockerung der Sicherheitsregeln.
Das Meta-SDK, Live-Polling und Bildnetzwerk sind absichtlich abgefangen/gesperrt:
entsprechende Lade-/Verbindungshinweise und ein nicht geladenes Prüfbild sind
Grenzen dieses Browseraufbaus, keine behaupteten realen Meta-Ausfälle.
Die geschützte Medienroute wurde separat mit simuliertem HTTP geprüft.
**Nicht geprüft:** heutiges echtes SDK, OAuth-Popup/Anmeldung und realer Meta-Callback.
Der historische SDK-Vertragsnachweis wird nicht als neuer Browserlauf gezählt.

## Neue Testzahlen, Beobachtbarkeit und Vorläufe

- Neue SQLite-Integration unter Windows/Python **3.14.3**, SQLite **3.50.4**:
  **3/3 bestanden**, 8,022 Sekunden.
- Gezielter Containerlauf: **146/146 bestanden**, 188,007 Sekunden; **54 PostgreSQL**
  und **92 SQLite-/datenbankunabhängige Fälle**. Darin die sechs neuen
  Integrationsausführungen und sechs extern geladenen Originalgegenproben.
- Vollständiger Abschlusslauf: **761/761 bestanden**, **347,713 Sekunden**;
  **90 PostgreSQL** und **671 SQLite-/datenbankunabhängige Fälle**, darin die
  neuen **3 SQLite- und 3 PostgreSQL-Integrationsfälle**. **0 Fehler, 0
  Fehlschläge, 0 Auslassungen.** Ein Lauf am 29. Oktober von
  **20:19:15 bis 20:25:03 UTC**, ohne Neustart oder diagnostischen Nachlauf.
- JavaScript: **62/62 bestanden**, Node.js **24.16.0**, 533,7794 ms; keine Auslassungen.
- Browser: 18 Zustands-/Breitenkombinationen plus Sync-Statusaktion. Ein erster
  erfolgreicher Lauf wurde um gezielt gescrollte Telefonausschnitte ergänzt und
  anschließend mit denselben fachlichen Assertions erneut ausgeführt.

Diese Gruppen überlappen; sie werden nicht addiert. Der vollständige Lauf verwendet
Python **3.12.13**, SQLite **3.46.1**, PostgreSQL **18.6**, psycopg **3.2.3** auf
frischer leerer Wegwerfdatenbank. Er ist keine komplette Anwendungssuite
ausschließlich auf PostgreSQL. Der lokale Starter schreibt UTC-Zeitstempel vor
und nach jedem Test unmittelbar in das Log. Er prüft Erreichbarkeit und Version
der Datenbank; der Docker-Starter prüft zusätzlich die leere öffentliche Schemafläche.
Der Abschlussabgleich zählt 761 Start- und 761 Ende-Einträge in derselben
Reihenfolge; der größte Abstand zwischen Logereignissen beträgt 16,498 Sekunden.
Echtes `urllib`-HTTP ist gesperrt. Testcontainer mounten nur benötigte Quellen
lesend, keine `.env` oder Kundendaten.

Für unerwartete generische HTTP 400 protokolliert der isolierte Harness ausschließlich
Ausnahmeklasse sowie Dateiname, Zeile und Funktion des Tracebacks beim bestehenden
Fehlerhandler. Kein Ausnahmetext, Token, Header oder Provider-Rohinhalt wird dafür
ausgegeben. Die Antwort und Produktlogik bleiben unverändert. Im vollständigen
Lauf entstanden genau zwei solche Diagnosen: der ausdrücklich simulierte
`RuntimeError` in `test_crash_nach_reservierung_bleibt_dauerhaft_unklar`, je einmal
auf SQLite/PostgreSQL, mit Ursprung in dessen Funktion `absturz`.
Beide erwarteten Crash-Fälle bestanden; es gab keine ungeklärte 400-Antwort.
Originalprotokolle der folgenden Entwicklungsfehler bleiben erhalten:

1. Erster neuer SQLite-Dreierlauf: ein FAIL, ein ERROR, ein bestandener Fall.
   Der Harness erwartete 403 statt sitzungsgebundenem eigenen Posteingang mit 200
   und verwendete die interne numerische Ticketzeile statt `ticket_id`.
   Korrigiert wurden ausschließlich neue Testannahmen und der Fixture-Zugriff;
   der Trennungsnachweis prüft nun Inhalt und unveränderten Zustand von A.
2. Zweiter Dreierlauf: zwei bestanden, ein FAIL. Die vorhandene Origin-Middleware
   weist bereits mit 403 ab, vor dem 409-Fehlerhandler der Anschlussroute.
   Die Erwartung wurde auf die tatsächlich geprüfte vorgelagerte Schutzgrenze angepasst;
   die fehlende Signatur wurde zugleich korrekt mit 403 geprüft.
3. Gezielter Zugriffslauf: ein FAIL, weil Rollenverlust die alte Sitzung ungültig
   macht und bereits zur Anmeldung umleitet (303). Der endgültige Test prüft
   sowohl diese ungültige alte Sitzung als auch einen neu angemeldeten Mitarbeiter,
   dem Anschluss und Synchronisierung mit 409 verwehrt bleiben.

Keine fachliche Produktassertion wurde abgeschwächt, kein bestehender Test geändert,
kein Timeout erhöht und kein Fehler automatisch erneut versucht. Nach den
Harness-Korrekturen bestanden die neue SQLite-Gruppe und der gezielte Containerlauf.

## Reproduktion und lokale Artefakte

Mit gepinnten Testabhängigkeiten, `APP_ENV=test`, leerem `DATABASE_URL` und einer
eigenen leeren PostgreSQL-Datenbank ausschließlich über
`WERKSTATTAI_TEST_POSTGRES_URL`:

```powershell
python -m unittest discover -s tests -p test_m2_gesamtabnahme.py -v
python -m unittest discover -s tests -v
python artifacts/m2-lokale-abnahme/postgres_pruefen.py test_m2_gesamtabnahme
python artifacts/m2-lokale-abnahme/postgres_pruefen.py
node --test tests/*.mjs
```

Die ersten beiden Aufrufe laden die eingecheckten Integrationstests beziehungsweise
die vollständige Suite. Ohne `WERKSTATTAI_TEST_POSTGRES_URL` werden PostgreSQL-Fälle
ausgelassen; das wäre kein vollständiger Abnahmenachweis. Die beiden Aufrufe von
`postgres_pruefen.py` benennen den hier verwendeten, absichtlich nicht
eingecheckten lokalen Docker-Starter. Er erzeugt seine eigene leere Datenbank
mit zufälligem Testpasswort, blockiert
echtes HTTP im inneren Starter und entfernt nur seine eigenen Ressourcen im
`finally`. Für die Browserquelle sind `WERKSTATTAI_PRUEFPLAYWRIGHT`,
`WERKSTATTAI_PRUEFCHROME`, `WERKSTATTAI_PRUEFPYTHON` und ein eigener ignorierter
`WERKSTATTAI_PRUEFAUSGABE`-Ordner explizit zu setzen; danach
`node tests/m2_browser_abnahme.cjs`.

Lokale Werkzeuge, Zeitprotokolle, Diagnose-/Bereinigungsnachweise und Screenshots
liegen in `artifacts/m2-lokale-abnahme/`, ausgeschlossen von Git und Docker-Images.
Die externen Originalgegenproben wurden nur bytegleich dorthin kopiert.
Beide Docker-Läufe entfernten ihre eigene PostgreSQL-Datenbank und ihr Netz im
`finally`; der Testcontainer wurde mit `--rm` beendet. Ein abschließender
Docker-Leseabgleich um **20:26:25 UTC** bestätigte die Abwesenheit aller Container
und Netze mit dem eigenen Präfix `werkstattai-m2-lokale-abnahme-20261029`.
Der eigene Chrome-Prozess wurde im `finally` geschlossen. Fremde Ressourcen
blieben unangetastet. Diff-, unveränderte Quellen- und Geheimnisprüfung ohne Befund;
nur die beiden neuen Testquellen und die beiden Dokumente werden veröffentlicht.

## Grenzen und spätere reale Abnahme

Kein bestätigter neuer blockierender Produktfehler in den abgeschlossenen
lokalen Kontrollen. Fehlende aktuelle Meta-Freigaben sind keine fehlgeschlagene
lokale Simulation. Nicht geprüft sind Kundenbetrieb, produktive Last,
tatsächliche Kontoeignung/-freigaben, aktuelle Geräteunterstützung und reale
Coexistence. Dafür wurden keine Kontoeinstellungen, Rechte, Nummernregistrierungen
oder echten Nachrichten ausgelöst.

Vor einem später ausdrücklich beauftragten realen Versuch kurz prüfen:

- Eigentümerautorisierung und aktuelle Eignung des Business-App-Anschlusses;
- tatsächliche Konto-/App-Zugriffe und aktuelle externe Voraussetzungen anhand
  offizieller Meta-Quellen;
- Nachrichten in beide Richtungen, Medien, Telefonübernahme, Duplikate und
  Trennung der beteiligten Konten.

Nicht unterscheidbare Provider-Generationen, gleichsekündige Mehrdeutigkeit,
fehlender globaler Kontaktabschluss, nicht verfügbare Medien und bereits
begonnenes externes HTTP bleiben ausdrücklich begrenzte Aussagen.
Grüne lokale Tests ändern `coexistence_bereit=0` im Produkt nicht und lösen
keine automatische Freigabe aus.

## Genau ein nächster Schritt

Unabhängige Bewertung dieses M2-Abnahmeberichts.
