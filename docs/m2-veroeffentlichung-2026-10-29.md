# M2: Veröffentlichungsversuche vom 29. und 30. Oktober 2026

## Nachtrag vom 30. Oktober, ab 17:28 CET: Railway-Paket übernommen

Das Paket des Beraterchats unter
`.m2-private/railway-bestaetigung-20261030T1607Z/BESTAETIGUNGSPAKET.md`
und `bestaetigung-ergebnis.json` ist ausgewertet. Seine Panelabrufe erfolgten
17:08–17:19 CET, der tatsächliche M1-Abgleich über TLS/READ ONLY um 17:14:51 CET.
Standardwerkstatt nicht demonstrativ, separate Demo, konfigurierte Nummer genau
einer Werkstatt zugeordnet, bestehendes M1-Token nicht leer. Keine reale
Meta-Token-/Berechtigungsprüfung oder Nachricht. Fehlende optionale Signup-Werte
blockieren das reine Code-Deployment bei nachgewiesen geschlossenem Signup nicht.

Private effektive Default-/Demo-/Nummernwerte für aktiven und Zielcommit lokal
mit der erfolgreichen Klonkonfiguration verglichen: alle drei identisch.
Keine Werte veröffentlicht. Erster eigener Vergleich behandelte die
`value`/`source`-Objekte fälschlich als Werte und stoppte mit `AssertionError`;
nach korrekter Strukturauswertung Vergleich erfolgreich. Kein Produktfehler.

Vorbereiteter gewöhnlicher Anwendungsrückweg unabhängig geprüft:
`6ea2fdc9dbac6cabaed07d391f598fafb0a9657a`, einziger Parent
`4eb8e3899314dc12d4af1d60fb0cf7b42e093b32`, vollständiger Baum exakt wie
`aa965e481f62ad34ee752d5b3cd89f365c4d30fb`. Privates Bare-Repository
`anwendungsrueckweg.git` im Paketordner. Der dokumentierte Push-Trockenlauf des
Beraterchats war erfolgreich; er garantiert keinen späteren Deployment-Erfolg.
Die bereits bestandene Laufzeitprobe des alten Codes auf migrierter echter Kopie
wird weiterverwendet. Nur im Incident-Fall nach erneutem Remote-Abgleich auf
exakt M2 den privaten Ref fetchen und den Folgecommit normal auf die bestehende
Produktionsbranch pushen. Keine Datenbankrücksicherung und kein Force-Push.

Quelle/Auto-Deploy/Wait-for-CI und ACTIVE-Deployment e81fee99 auf vollem aa965e4
sind durch das Paket zeitgebunden belegt; kein sichtbarer offener Änderungsstand
beim damaligen Abruf. Erneuter eigener Git-Abgleich bestätigt unverändert
Produktion aa965e4, Ziel 4eb8e38, 0/16. Der Beraterchat hat Zugang zu Übersicht,
Deploymentdetails und Logs; seine Beobachtung des neuen Rollouts muss tatsächlich
erfolgen. Kein eigener Browserzugriff daraus abgeleitet.

**Noch kein Produktionspush:** Der ausdrücklich geforderte unmittelbare
Panelabgleich wurde um 17:28 CET über Mikołaj angefragt, einschließlich verfügbarer
Rolloutbeobachtung. Keine neue allgemeine Veröffentlichungsfreigabe verlangt.
Sicherung, Klonmigration und Laufzeitnachweise aus bf008e13 bleiben gültig;
ihre Aktualität ist vor Promotion zu berücksichtigen. `coexistence_bereit=0` bleibt.

**Genau ein nächster Schritt:** Den angefragten aktuellen Panelabruf übernehmen
und bei unverändertem Ausgangsstand den beauftragten Fast-forward/Produktionspush
durchführen.

## Fortsetzung vom 30. Oktober 2026: Produktionskopie geprüft, Promotion offen

**Kein Produktionspush, kein neues Deployment und keine Produktionsmigration.**
Der direkte Datenbankzugang funktioniert; fehlende Railway-Nachweise blockieren
weiterhin die Promotion. Die folgenden Ergebnisse ergänzen die unverändert
erhaltene Historie vom 29. Oktober. Keine erneute allgemeine Freigabe erforderlich.

### Tatsächliche Produktionsdaten und Sicherung

Am 30.10. um 17:06 CET erneut PostgreSQL **18.6**, TLS und ausdrücklich
READ ONLY bestätigt: **2 Werkstätten, 1 Demo, 1 nicht leere Phone Number ID**.
Exakte Python-strip-Normalisierung: **0 Konfliktgruppen, 0 Änderungen an Phone
Number IDs**. Dies ist kein Abgleich mit den tatsächlichen Railway-App-Werten.
Keine Kundendublettenbereinigung oder Produktionsänderung vorgenommen.

Neue Sicherung abgeschlossen **17:06:21 CET**, Custom-Archiv **56.878 Bytes**,
SHA-256 `3a609eaf7be4472e18a0a659671961b62010814d7b79a9149c92af8631489018`.
Private Ablage außerhalb des Repositories unter
`C:\Users\Mikolaj\Documents\New project\.m2-private\ausfuehrung-20261030T160555Z\sicherung-20261030T160555Z\produktion.dump`.
Git-Ausschluss vor Nutzung bestätigt. `pg_restore --exit-on-error --no-owner
--no-acl` erfolgreich; **11 Tabellen, 365 Zeilen** lesbar. Ergebnis und Rohbelege
liegen ausschließlich privat. Ältere Sicherung mit 364 Zeilen und SHA-256
`0133f853903a3a227217a44b2c40bd2a9252655f51a453d914330319a41aa2fc` erhalten.
Die unterschiedliche Zeilenzahl ist keine Behauptung über ihre Ursache.
Keine clusterweite Rollen-/PITR-Sicherung; kein Recht, neuere Schreibvorgänge
durch Rücksicherung zu überschreiben. Vor späterer Promotion Aktualität bewerten.

### Migration der echten Kopie und Anwendungsrückweg im Klon

Vorige Prüfimages waren entfernt; deshalb beide exakten Gitarchive mit dem
unveränderten Dockerfile erneut gebaut, jeweils Exitcode 0 (17:05 CET):

| Stand | Image-ID |
| --- | --- |
| M2 `4eb8e3899314dc12d4af1d60fb0cf7b42e093b32` | `sha256:9ef95bd106b87ad93352d96419f740f5fdf9feb85bda039cbbfbb327cd994cd5` |
| Vorgänger `aa965e481f62ad34ee752d5b3cd89f365c4d30fb` | `sha256:0cfa95725e14f0ff8dd7e7f149c0243f3b8d94e02a3b48c1c88b02bb0973ceec` |

Revisionslabels geprüft, Ziel-cryptography **50.0.2** bestätigt. Bildtags
`werkstattai-m2-veroeffentlichung-{ziel,vorgaenger}:20261029` bleiben zur
Fortsetzung lokal erhalten; ihr Datum bezeichnet nicht diesen neuen Bauzeitpunkt.
Nur getrackte Commitquellen im Buildkontext; keine Sicherungen oder Geheimnisse.

Frische interne Docker-Netze ohne Hostports, PostgreSQL im tmpfs; echte Kopie
mit aus der Datenbank abgeleiteten Test-IDs und synthetischen Geheimnissen.
Kein externer Meta-/WhatsApp-/KI-Zugriff. Diese Testkonfiguration beweist keine
produktive App-Konfiguration.

**Originalfehler erhalten:** Erster Lauf 17:11 CET startete M2 erfolgreich,
stoppte aber beim strikten Vergleich alter Spaltenwerte mit `AssertionError`,
Exitcode 1. Nur `workshops` abweichend, Zeilenzahlen und Sequenzen gleich.
Keine Produktkorrektur. Die getrennte Diagnose berücksichtigte ausschließlich
die bereits implementierte Normalisierung der beiden Nummernfelder
(`normalisiere_nummernwert` in `app/whatsapp_verbindungen.py`).

**Getrennter erfolgreicher Lauf 17:12–17:13 CET, Exitcode 0:** genau **1**
Normalisierung von `whatsapp_display_phone_number`, weiterhin **0** Änderungen
an `whatsapp_phone_number_id`. Nach dieser vorgesehenen Normalisierung stimmen
alle bisherigen Spaltenwerte einschließlich IDs in allen **11** alten Tabellen
und sämtliche Sequenzpositionen überein. Es wird kein bytegleicher Erhalt des
einen normalisierten Anzeigefeldes behauptet.

Zusätzlich bestanden:

- Sieben M2-Tabellen vorhanden; M1 im Klon als `m1_legacy`/`altbestand`
  auflösbar und Zugang verwendet das synthetische M1-Token der Testkonfiguration.
- Getrennte Default-/Demo-Werkstatt, Signup ohne optionale Konfiguration geschlossen,
  alle vorhandenen Verbindungen mit `coexistence_bereit=0`.
- Wiederholter M2-Start ohne weitere Änderung am geprüften Altbestand.
- Exakter Vorgängercode auf derselben migrierten Kopie startet und bleibt nutzbar;
  kein Schema-Downgrade und keine Datenbankrücksicherung erforderlich.
- Lokale HTTP-Kontrollen für M2 und Vorgänger: Health/Loginseite/Dashboard/
  Einstellungen erfolgreich; Medien ohne Anmeldung 303, angemeldet für nicht
  vorhandenes Medium 404. M2-Anschlussansicht zeigt fehlende Einrichtung.

Angemeldete Klonprüfungen nutzten ausschließlich lokal signierte Testsitzungen
mit synthetischem Schlüssel. **Kein Passwortlogin und keine angemeldete
Produktionsprüfung**. Bestehendes Benutzerpasswort nicht ersetzt.

Alle eigenen Sicherungs-, ersten und zweiten Migrationscontainer sowie Netze
entfernt; Abwesenheit jeweils bestätigt. Private Archive und Originalprotokolle
erhalten, temporäre Verbindungs-/Passwort-/Env-Dateien entfernt. Belege in
`ausfuehrung-20261030T160555Z/{migrationsprobe,migrationsprobe-normalisierung}`;
ignorierte Helfer und Buildprotokolle in `artifacts/m2-veroeffentlichung-2026-10-30`.

### Produktionsstand und konkret fehlende Railway-Nachweise

Erneuter Remote-Abgleich um 17:13 CET bestätigt unverändert:

- Produktion `codex/kundenkommunikation-2026-09-26`:
  `aa965e481f62ad34ee752d5b3cd89f365c4d30fb`.
- M2 `codex/m2-lokale-abnahme-2026-10-29`:
  `4eb8e3899314dc12d4af1d60fb0cf7b42e093b32`, 16 voraus/0 zurück,
  Produktion direkter Vorfahr. Berichtsbranch zu Beginn sauber auf
  `0aa7831c166953a1c0d4db9be1fb488e55ad8692`.

Öffentliche Livekontrolle 17:13 CET: `/health` 200, `/login` 200,
`/dashboard/whatsapp/medien/0` ohne Anmeldung 303 zur Loginseite. Das beweist
weder aktuellen Deployment-SHA noch Migration oder produktive M1-Auflösung.
Letzte übergebene Railway-ID weiterhin
`e81fee99-9838-4ee3-9639-ba2674b3537b`, damals ACTIVE/successful auf dem Vorgänger;
heute in dieser Sitzung nicht neu bestätigt. Keine neue Deployment-ID.
[Bestehende App](https://werkstattai-whatsapp.up.railway.app).

Auch eine neue In-App-Karte meldet in dieser Sitzung
`The browser access host is unavailable`. Die funktionierende Sitzung des
Beraterchats bleibt getrennt. Native Chrome-Sicherheit, Windows-Anwendungskontrolle
und Ausführungsrichtlinie unangetastet; keine Railway-CLI oder Tokenumgehung.

**Benötigtes gemeinsames Nachweispaket für den Beraterchat:**

1. Tatsächlich wirksame `DEFAULT_WORKSHOP_ID`/`DEMO_WORKSHOP_ID` gegen die
   bestehende nicht demonstrative M1-Werkstatt und Demo prüfen; gespeicherte
   normalisierte Nummer gegen `WHATSAPP_DEFAULT_PHONE_NUMBER_ID` vergleichen.
   Vorhandenes verwendetes M1-Token und effektive Signup-Konfiguration bestätigen.
   Geheimnisse, vorhandenen Verschlüsselungsschlüssel und Graph-Version erhalten;
   Werte nur lokal privat, im Bericht nur Prüfurteile und Anzahlen.
2. Aktuelle Railway-Quelle, Auto-Deploy/Wait-for-CI, vollständigen aktiven SHA,
   Deployment-ID und fehlende fremde ausstehende Änderungen belegen; unmittelbar
   vor dem beauftragten Produktionspush erneut abgleichen.
3. Gewöhnlichen ausführbaren Rückweg zum geprüften Vorgänger sowie verfügbaren
   Zugang zur Beobachtung und Abschlussprüfung des neuen Deployments konkret
   bestätigen. Ein Redeploy-Menü allein genügt nicht. Die Eignung des alten Codes
   auf der migrierten Kopie ist jetzt belegt; die Railway-Ausführung noch nicht.

**Genau ein nächster Schritt:** Dieses konkrete Railway-Nachweispaket über den
bereits autorisierten Beraterchat beschaffen und damit Auftrag 06 ab der
verbliebenen Produktionsvorprüfung fortsetzen. Bis dahin keine Promotion;
`coexistence_bereit=0`, reale Coexistence bleibt separat offen.

## Historischer Veröffentlichungsversuch vom 29. Oktober 2026

## Ergebnis

**Vor der Produktionsänderung konkret blockiert. Kein Produktionspush, kein
Railway-Deployment und keine Produktionsmigration ausgeführt.** Die lokale
M2-Abnahme bleibt gültig; sie ersetzt die noch fehlende Produktionsvorprüfung
nicht. Der Auftrag zur Veröffentlichung liegt vor. Es fehlt ein funktionsfähiger
autorisierter Zugriff auf Railway und damit auf die erforderlichen Nachweise.

Die unabhängig möglichen Kontrollen wurden ausgeführt: beide genauen
Commitarchive gebaut, künstlichen PostgreSQL-Altbestand gesichert und getrennt
wiederhergestellt, M2-Migration und wiederholten Start geprüft sowie die alte
Anwendung auf dem migrierten künstlichen Bestand gestartet. Diese Ergebnisse
sind **kein Sicherungs-, M1- oder Migrationsnachweis der Produktionsdatenbank**.

## Grundlage und aktueller Git-Abgleich

Gelesen: `AGENTS.md`, `docs/projektstand.md`, der
[lokale Abnahmebericht](m2-lokale-abnahme-2026-10-29.md), der unabhängige Bericht
`m2-gesamtabnahme-review-2026-10-29/PRUEFBERICHT.txt` und der vorbereitete
`m2-merge-plan-2026-10-29/PLAN_KONTROLOWANEGO_MERGE.txt` im lokalen Dokumentordner.
Die unabhängige Bewertung nimmt Aufgabe 5 lokal an. Frühere **761/761 Python**
mit 90 PostgreSQL sowie unabhängige **80/80**, **62/62 JavaScript** und Chrome
sind historische, überlappende Nachweise; diese Suiten wurden hier nicht wiederholt.

Eigene Abfrage mit `git ls-remote --heads origin` bestätigt:

| Rolle | Branch | Vollständiger SHA |
| --- | --- | --- |
| Produktion | `codex/kundenkommunikation-2026-09-26` | `aa965e481f62ad34ee752d5b3cd89f365c4d30fb` |
| Lokal abgenommenes M2 | `codex/m2-lokale-abnahme-2026-10-29` | `4eb8e3899314dc12d4af1d60fb0cf7b42e093b32` |

Zu Beginn sauberer Arbeitsbaum auf dem M2-Commit. `git merge-base --is-ancestor`
bestätigt den direkten Vorfahren; `git rev-list --left-right --count` ergibt
**0 / 16**. Keine fremden lokalen Änderungen vorgefunden. Die beiden
Produktbranches wurden nicht verändert; `master` blieb unberührt.
Dieser Bericht entsteht auf `codex/m2-veroeffentlichungsbericht-2026-10-29`,
ausgehend vom abgenommenen M2-Commit, getrennt von der Produktionsbranch.

## Konkrete Zugriffssperre

Die vorhandene Browsersteuerung liefert `apps: []` und `browsers: []`.
Das Öffnen des benannten Railway-Projekts endet mit
`Browser is not available: iab`. Die zulässige native Fenstersteuerung scheitert
bereits bei der Initialisierung mit
`windows sandbox failed: CreateProcessWithLogonW failed: 2`.
Ein Reset und eine einzelne Wiederherstellungsprobe ergaben denselben Fehler.
Nach dem Angebot des Nutzers, beim Login zu helfen, wurde die Browserinventur
erneut geprüft: weiterhin keine verfügbare Oberfläche. Der Nutzer sieht keine
Möglichkeit, eine Karte für diese Sitzung freizugeben. Ein Login konnte daher
gar nicht begonnen werden; es liegt keine nachgewiesene Ablehnung des Kontos vor.

Die bekannte Windows-Anwendungskontrollsperre der Railway CLI wurde nicht
umgangen; keine CLI ausgeführt, keine Schutzregeln geändert und kein alternativer
Zugriff aus ausgelesenen Sitzungstokens aufgebaut. Die vorhandenen lokalen
Railway-Prüfwerkzeuge hängen ebenfalls an dieser CLI. In Projekt-`.env` und
Prozessumgebung ist keine `DATABASE_URL` gesetzt; im Prozess kein Railway-Token.
Das ist **keine Aussage über die tatsächlichen Railway-Variablen**.

## Produktionsvoraussetzungen und Status

| Erforderlicher Nachweis | Ergebnis dieses Auftrags |
| --- | --- |
| Aktuelle Railway-Quelle und fremde ausstehende Änderungen | Blockiert, Panel nicht erreichbar |
| Aktives Deployment und tatsächlich laufender Commit | Nicht erneut bestätigt |
| Aktuelle PostgreSQL-Sicherung und isolierte Wiederherstellung dieser Sicherung | Nicht ausgeführt, Produktionszugriff fehlt |
| Anzahl mehrfach gebundener normalisierter Phone Number IDs | Nicht geprüft; keine Konfliktanzahl für Produktion behauptet |
| Bestehender M1-Bezug, gespeicherte Nummer, getrennte Default-/Demo-Werkstatt | Nur künstlich geprüft; produktiver Nachweis fehlt |
| Vorhandene Secrets, Schlüssel und Graph-/Signup-Konfiguration | Nicht geprüft und nicht verändert |
| Migration mit tatsächlichem Altbestand und Daten-/Schlüsselerhalt | Nicht geprüft; nur synthetischer Übergang belegt |
| Wiederherstellbarkeit des guten Railway-Deployments | Nicht im Panel bestätigt |
| Fast-forward/Produktionspush/Deployment | Nicht ausgeführt, Voraussetzungen fehlen |

**Historischer Railway-Stand aus der übergebenen Planung:** Projekt
`surprising-warmth`, Umgebung `production`, Dienst `WerkstattAI`, Quelle
`codex/kundenkommunikation-2026-09-26`; automatisches Deployment bei Push,
Wait for CI ausgeschaltet. Letztes bestätigtes aktives Deployment
`e81fee99-9838-4ee3-9639-ba2674b3537b` auf `aa965e4` vom 19. Oktober.
Diese Angaben wurden heute in diesem Auftrag nicht durch einen Panelzugriff
erneut verifiziert. Es gibt keine neue Deployment-ID.

[Railway-Projekt](https://railway.com/project/42bbbeae-632d-44e5-b55b-f676745f4ad6)
und [bestehende Anwendung](https://werkstattai-whatsapp.up.railway.app).

## Tatsächlich ausgeführte lokale Bau- und Migrationsprobe

Mit `git archive` wurden ausschließlich getrackte Quellen der beiden genannten
SHA an `docker build` übergeben. Vorhandenes unverändertes `Dockerfile`, keine
Produktionsdaten, `.env` oder Rohartefakte im Kontext. Beide Builds bestanden:

- Ziel: 22:00:19 bis 22:01:41 UTC, Bildkennung
  `sha256:b90b649a229f54091ebd6f4f0f6ad84fbbe8cd0dcddd34e45931e1442d07843d`.
- Vorgänger: 22:01:41 bis 22:02:19 UTC, Bildkennung
  `sha256:66bc8e7d8ac44c85920ea7762befe633653a24966474626cf332d1b5112af1b8`.
- Das vorhandene bewegliche Basisimage `python:3.12-slim` lieferte bei diesem
  Build Python **3.12.16**. Im gestarteten Ziel wurde **cryptography 50.0.2**
  bestätigt. Das behauptet keine unveränderliche Basisimage-Version für spätere Builds.

Eigener PostgreSQL-Container `postgres:18-alpine`, temporärer Datenbestand,
eigenes **internes Docker-Netz ohne externe Erreichbarkeit**, keine veröffentlichten
Ports. Ausschließlich synthetische Zugangsdaten und getrennte Default-/Demo-IDs;
optionale neue Signup-Einstellungen bewusst nicht gesetzt. Keine externen
Meta-Aufrufe möglich. Der lokale Ablauf zwischen 22:03:54 und 22:04:35 UTC:

| Kontrolle | Beobachtetes Ergebnis |
| --- | --- |
| Vorgängerstart mit `APP_ENV=production` | Startup erfolgreich; Health, Login, Dashboard, Einstellungen und Mediensperre geprüft |
| Künstlicher Altbestand | Eigene M1-Werkstatt, öffentliche Demo, Benutzer, Ticket, Nachricht und Sitzung im alten Schema |
| `pg_dump -Fc --no-owner --no-acl` und `pg_restore --exit-on-error` | Künstliche Sicherung erfolgreich in zwei getrennte Datenbanken wiederhergestellt; eine für Migration, eine für Konfliktprobe |
| Zielstart auf wiederhergestelltem Altbestand | Startup und M2-Tabellen vorhanden; alle vorherigen Spaltenwerte der fünf geprüften Tabellen `workshops`, `users`, `tickets`, `whatsapp_messages`, `conversation_sessions` erhalten |
| M1 und geschlossener Signup | Herkunft `m1_legacy`, Autorisierung `altbestand`, vorhandener synthetischer Token unverändert auflösbar; Default/Demo getrennt; `eingerichtet()` falsch und Anschlussseite zeigt fehlende Einrichtung |
| Coexistence | Keine Verbindung mit Flagge ungleich 0; keine Freigabe gesetzt |
| Angemeldete HTTP-Kontrolle | Health, Login, Dashboard, Einstellungen, neue Anschlussansicht; Medien ohne Anmeldung zur Loginroute, angemeldet für nicht vorhandene ID 404 |
| Zweiter Zielstart | Geprüfte Tabellen unverändert, M1 und Sperren weiter korrekt |
| Alter Anwendungscode auf migrierter Kopie | Startup, gleiche geprüfte Tabellenwerte und HTTP-/Login-/Datenbankzugriff erfolgreich; kein Schema zurückgelöscht |
| Doppelte Werkstattbindung mit Leerraum | Eine künstliche Konfliktgruppe; Zielmigration verweigert, ursprünglicher Nummernwert unverändert. Keine Auswahl eines Besitzers |

Die Konfliktprobe verwendet dieselbe fachliche Normalisierung wie die Migration:
`str(wert or "").strip() or None`. Sie betrifft Werkstattbindungen, keine
doppelten Kundenkontakte. Die künstliche Zahl **1** ist kein Produktionsbefund.
Lokale HTTP-Tests verwenden den vom echten Login ausgegebenen Sitzungscookie
über Loopback; sie sind kein neuer Browser- oder TLS-Nachweis.

**Fehlerprotokoll bleibt erhalten:** Nach allen fachlichen Assertions trat im
eigenen Starter bei der Bereinigungsprotokollierung ein
`TypeError: melde() got multiple values for argument 'name'` auf. Der Lauf endet
deshalb mit Exitcode 1 und wird nicht als insgesamt grüner Testprozess ausgegeben.
Die Datenbank war bereits entfernt, das Netz blieb zunächst bestehen.
Nur der lokale Hilfsparameter wurde korrigiert und die Fortschrittsdatei künftig
pro Ereignis geschrieben. Kein Produktcode geändert und kein erneuter kompletter
Migrationslauf zum Verdecken des Fehlers. Die Bereinigung wurde gezielt separat
abgeschlossen und kontrolliert. Eine erste rein lesende Docker-Formatabfrage
scheiterte zusätzlich an PowerShell-Quoting; die anschließende JSON-Abfrage
lieferte die Bildkennungen und Commitlabels korrekt.

## Öffentliche Anwendung und Bereinigung

Eigene ausschließlich lesende HTTPS-Abfrage am 29. Oktober um **22:04:27 UTC**,
mit ausgewiesenem Prüfclient:

- `/health`: HTTP 200 und `ok=true`.
- `/login`: HTTP 200.
- `/dashboard/whatsapp/medien/0`: zur Loginseite umgeleitet; abschließend HTTP 200
  auf `/login`, kein Medieninhalt abgerufen.

Das belegt Erreichbarkeit und Anmeldungsschutz der bestehenden Anwendung,
**nicht** deren Commit, erfolgreichen Datenbankzugriff oder eine M2-Migration.
Kein angemeldeter Produktions-Dashboard-/Einstellungs-/Anschlussnachweis möglich.

Abschließende Docker-Kontrolle um **22:05:39 UTC**: eigene App- und
PostgreSQL-Container sowie das Prüfnetz abwesend; die zwei ausdrücklich
gekennzeichneten Prüfbildtags entfernt und ihre Abwesenheit bestätigt.
Keine fremden Ressourcen oder produktiven Wiederherstellungspunkte verändert.
Lokale Archive, synthetischer Dump, Bau-/Fehlerlogs und Hilfswerkzeuge liegen
ignoriert unter `artifacts/m2-veroeffentlichung/`, außerhalb von Git und Images.

## Rückweg, Dokumentation und Fortsetzung

Es gab keine Produktionsänderung, daher auch keinen produktiven Rollback.
Der Start des alten Codes auf der migrierten **künstlichen** Kopie ist belegt.
Vor einem späteren Produktionspush muss die tatsächliche Wiederherstellbarkeit
des genannten guten Deployments im Railway-Panel bestätigt werden. Ein
Anwendungsrollback ersetzt keine Wiederherstellung der separaten PostgreSQL-Datenbank.
Eine solche Wiederherstellung über neuere Schreibvorgänge hinweg darf nicht
automatisch erfolgen; Datenverlust und Erhalt neuerer Daten sind vorher zu entscheiden.
Bestehende Verschlüsselungsschlüssel und Zugangsdaten erhalten.

Projektzentrum und M2-Karte in Notion wurden mit Beginn, konkreter Zugriffssperre
und anschließendem Ergebnis aktualisiert. Keine Secrets, Kundeninhalte oder
privaten Rohlogs veröffentlicht. Dieser Bericht und der Projektstand sind die
einzigen eingecheckten Änderungen der getrennten Berichtsbranch. Diff- und
Geheimnisprüfung ohne Befund. Keine Änderung von Meta, Kontorechten, Telefonnummern,
Produktkonfiguration oder `coexistence_bereit`; keine echten WhatsApp-Nachrichten.

**Genau ein nächster Schritt:** Einen funktionsfähigen autorisierten
Railway-Zugriff für diese Sitzung bereitstellen, damit die fehlende
Produktionsvorprüfung und die bereits beauftragte Veröffentlichung fortgesetzt
werden können.
