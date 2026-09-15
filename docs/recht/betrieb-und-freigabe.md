# Datenschutz: Umsetzung, Bearbeitung und offene Angaben

Stand: 15. September 2026. Technische Vorbereitung und Entwürfe; kein
Rechtsgutachten und keine Zusage vollständiger DSGVO-Konformität.

## Was vorbereitet ist

- `/impressum`: DDG-Anbieterinformationen mit ausdrücklich offenen Angaben.
- `/datenschutz`: Datenflüsse, Verantwortlichkeiten, Speicherungen, Empfänger,
  Drittlandverarbeitung, Rechte und derzeitige technische Grenzen.
- `/datenschutz/rechte`: öffentlicher Kontakt- und Bearbeitungsweg.
- `/dashboard/privacy`: geschützter Gesamtexport und Kundenexport mit Vorschau,
  Löschung ausgewählter aktiver Daten und Download der AVV-Grundlage.
- `avv-grundlage.md`: Vertragsentwurf mit Verarbeitungsbeschreibung,
  Dienstleisterregister, TOM-Stand und auszufüllenden Fristen.

Anbieterangaben werden über `LEGAL_*` aus `.env.example` gepflegt. Sie werden
niemals aus der Demowerkstatt übernommen. Noch fehlende Anschrift/Rechtsform
bleiben als Platzhalter sichtbar. Das Vorhandensein aller Felder alleine macht
die Entwürfe noch nicht rechtlich geprüft; der Entwurfsstatus wird bewusst nicht
automatisch entfernt.

Die Wirtschafts-Identifikationsnummer kann, soweit vorhanden und anzugeben,
über `LEGAL_BUSINESS_ID` ergänzt werden; `LEGAL_VAT_ID` bleibt für die USt-IdNr.
zuständig. Fehlende Angaben werden nicht aus anderen Betriebsdaten abgeleitet.

Der Cloudflare-Worker enthält keine eigene Kopie der Rechtstexte mehr. Seine
Rechtsseiten verweisen per temporärer Weiterleitung auf dieselben Seiten der
Anwendung. Beim späteren Deployment zuerst die Anwendung aktualisieren, dann
den Worker. Für Meta die Datenschutz-URL der Anwendung hinterlegen und prüfen;
Erreichbarkeit und Rate-Limits dieser Anwendung gelten auch nach der Weiterleitung.

## Datenbestand und Abdeckung

| Tabelle | Export | Löschung über Kundenauswahl |
| --- | --- | --- |
| workshops | Eigene Betriebsdaten im Gesamtexport | Nein, Konto bleibt bestehen |
| users | E-Mail, Werkstatt, Rolle, Zeitpunkte; niemals password_hash | Nein |
| tickets | Alle Felder, einschließlich JSON-Notizen und Rückfragen | Über vollständige Ticket-ID / Telefonnummer |
| conversation_sessions | Gesprächsstand und Kennungen | Über Telefonnummer / Ticketbezug |
| whatsapp_messages | Nachrichten und technische Payloads | Über Telefonnummer / Ticketbezug |
| whatsapp_events | Ereignisse und technische Payloads | Über Telefonnummer / bekannte Nachrichtenkennung |
| whatsapp_conversation_controls | Modus und Ticketzuordnung | Über Telefonnummer / aktiven Ticketbezug |
| rate_limit_buckets | Kein Kundenexport; nur HMAC-Kennungen | Automatischer Ablauf bei Folgeanfragen |
| ticket_sequences | Technischer Nummernzähler, keine Kundeninhalte | Nicht löschen, Nummern nicht wiederverwenden |
| privacy_operations | Minimierter Vorgangsvermerk, nicht im Kundendownload | Separate 90-Tage-Bereinigung bei nächstem Export/Löschvorgang |

Die Zuordnung ist keine Volltext-Personensuche. Andere Telefonnummern,
unverknüpfte alte Datensätze, Erwähnungen in fremden Notizen und Daten ohne
Kontakt-/Ticketbezug benötigen ergänzende manuelle Prüfung. Eine Ticket-ID wählt
einen Vorgang aus, nicht automatisch alle Daten derselben Person.
Eine Telefonnummer kann gemeinsam genutzt werden: Treffer vor jeder Weitergabe
oder Löschung prüfen. Keine pauschale Aussage „alles gelöscht“ allein aufgrund
einer leeren Vorschau.

Gesamtexporte sind für berechtigte Werkstattinhaber bestimmt und enthalten Daten
mehrerer Personen. Auch Kundenexporte müssen vor Weitergabe auf Rechte Dritter,
interne Notizen und technische Inhalte geprüft werden. Art. 15-Auskunft und
Art. 20-Datenübertragbarkeit sind rechtlich nicht identisch.

## Vorgehen bei Auskunft / Löschung

1. Eingang und zuständige Werkstatt in einem geschützten Vorgangsnachweis
   erfassen. Eingangsdatum und Frist überwachen. Keine Kundenanfragen in GitHub.
2. Identität risikogerecht prüfen, bei berechtigten Zweifeln nur notwendige
   Zusatzinformationen erheben. Keine pauschalen Ausweiskopien verlangen.
3. Vollständige Telefonnummern, Ticket- und gegebenenfalls Demo-Session-IDs
   zuordnen; Vorschau in der betreffenden Werkstatt öffnen. Demo-Anfragen ohne
   Konto werden betreut anhand der angegebenen Session-ID bearbeitet.
4. Auskunft vor Weitergabe prüfen und über einen abgestimmten sicheren Weg
   liefern. Die generierte Datei ist eine Arbeitskopie, keine fertige Antwort.
5. Für Löschung Rechtsgrundlage und Ausnahmen prüfen. Bei Aufbewahrungspflichten
   erforderliche Daten separat beschränken; keine pauschale Löschung ausführen.
   Die Anwendung bietet noch keine eigene Sperre für Aufbewahrungspflichten.
6. Vorschau, ausdrückliche Bestätigung und aktuelles Passwort verwenden.
   Bei Änderungen neue Vorschau erstellen. Die Anwendung löscht nur die
   bestätigte Auswahl in einer Transaktion; andere Werkstätten bleiben unberührt.
7. Externe Bestände, Hosting-/Worker-Logs, Backups, E-Mail, WhatsApp und lokale
   Exporte gesondert prüfen. Erforderliche Empfängerbenachrichtigungen nach
   Art. 19 DSGVO veranlassen. Das Programm versendet keine solchen Nachrichten.
8. Maßnahmen, Ausnahmen und noch verbleibende Fristen im geschützten Nachweis
   dokumentieren und an die betroffene Person mitteilen. Grundsätzlich innerhalb
   eines Monats; notwendige Verlängerungen fristgerecht begründen.

Der Anwendungsnachweis enthält nur Werkstatt, pseudonymisierten Bearbeiter,
Aktion, Mengen und Zeitpunkt. Er speichert absichtlich keine gelöschten
Kundeninhalte und ersetzt keine vollständige Fallakte. Sichere externe
Vorgangsnachweise und deren Fristen müssen betrieblich geregelt werden.

## Backups und Vertragsende

Eine Live-Löschung entfernt keine Sicherung. Für jeden Speicherort müssen
verbindliche Fristen, beschränkter Zugriff und ein Verfahren zur Wiederanwendung
von Löschungen bei Restore vereinbart werden. Vor Wiederfreigabe eines Restores
die seit dem Sicherungszeitpunkt bearbeiteten Lösch-/Einschränkungsanfragen aus
dem separat gesicherten Vorgangsnachweis erneut anwenden und kontrollieren.
Es wurde kein produktives Backup gelöscht, kein automatischer Bereinigungsjob
aktiviert und keine nachträgliche Löschfrist erfunden.

Bei Vertragsende zuerst Wahl des Auftraggebers (Rückgabe / Löschung) und
Aufbewahrungspflichten klären. Der Gesamtexport deckt die aktiven Anwendungsdaten
ab. Die endgültige Kontoschließung einschließlich Benutzer und verbleibender
Bestände ist ein betreuter Vorgang, keine Schaltfläche dieser Umsetzung.

## Vor Abschluss / regulärem Echtbetrieb offen

- Anbieteridentität, Geschäftsanschrift, Rechtsform und optionale Register-/Steuerangaben bestätigen.
- Individuelle Werkstatt-Verantwortliche und Datenschutzhinweise vollständig hinterlegen.
- Railway-DPA und konkret einschlägige Transfergrundlage dokumentieren; Hosting
  und DB sind im bisherigen Arbeitsstand mit us-west2 / USA vermerkt; die aktuelle
  Kontokonfiguration konnte lokal nicht erneut verifiziert werden. Ein Umzug in eine EU-Region wäre ein
  eigener Infrastrukturvorgang und beseitigt nicht automatisch alle Drittlandbezüge.
- Cloudflare-Worker-Code, Logging, Kontobedingungen und Datenverarbeitungsvertrag prüfen.
- WhatsApp-Kontoinhaber, Vertragspartner, Rollen und Löschwege bestätigen.
- Outlook-Kontotyp und vertragliche Eignung für geschäftliche Datenschutzanfragen prüfen.
- Aufbewahrungs-/Prüffristen, Backups, Wiederherstellung, Vorfallprozess und
  Verzeichnis der Verarbeitungstätigkeiten festlegen.
- Bestehendes Admin-Passwort auf einen etwaigen Standardwert prüfen und gegebenenfalls ändern; öffentliche Ticketabrufe vollständig
  auf Berechtigung prüfen. Diese Vorbereitung ist keine umfassende Sicherheitsabnahme.
- Rechtsprüfung der ausgefüllten Texte, AVV-Anlagen und tatsächlichen Abläufe.

## Technische Grenzen und Testhinweise

Die Oberfläche begrenzt direkte Exporte auf 10.000 Betriebsdatensätze und
20 MiB pro Datei. Größere Bestände benötigen einen betreuten Export; es gibt
keine unbemerkte Teilausgabe. Die Bestätigung läuft nach zehn Minuten ab, bindet
Nutzer, Werkstatt und Datenstand und kann nicht für eine andere Auswahl benutzt
werden. Passwortprüfungen zur Löschung sind auf fünf je 15 Minuten und Benutzer
begrenzt. Bereits geänderte/entfernte Benutzer werden abgewiesen.

Tests ausschließlich mit isolierten Testdaten ausführen. Produktive Exporte
nicht für Screenshots herunterladen und Kundendaten nicht in Testdateien kopieren.

### Lokaler Prüfumfang vom 15. September 2026

Ergebnis: **163 Python-Tests und 3 Worker-Tests erfolgreich**.

- `tests/test_privacy.py`: öffentliche Rechtstexte, Anbieterfelder und Escaping;
  Anmeldung, Werkstattgrenzen und geänderte/entzogene Rollen; vollständiger und
  ausgewählter Export; Passwort, Bestätigung, abgelaufene/manipulierte Tokens;
  Änderungen seit der Vorschau; Passwort-Rate-Limit, Größenlimits und Rücknahme
  der gesamten Löschung bei einem Fehler im Vorgangsvermerk. Auch beschädigtes
  Session-JSON blockiert die Zuordnung anhand einer gespeicherten Telefonnummer
  nicht mehr. Nicht zuordenbare Daten benötigen weiterhin manuelle Prüfung.
- `tests/test_privacy_worker.mjs`: Weiterleitung aller Rechtsseiten einschließlich
  HEAD-Anfragen, Entfernung fremder Query-Parameter, Meta-Verifikation und
  unveränderte Weiterleitung signierter Webhook-Inhalte.
- Reproduzierbar mit `python -m unittest discover -s tests -q` und
  `node --test tests/test_privacy_worker.mjs`. Die Python-Suite erstellt eigene
  temporäre SQLite-Datenbanken und überschreibt dafür `DATABASE_URL`.
- Lokale Umgebung: Python 3.14, FastAPI 0.115.0, Pydantic 2.12.5, Node 24.
  Ein Abgleich mit den vollständig gepinnten Docker-Abhängigkeiten unter Python
  3.12 und ein PostgreSQL-Integrationstest stehen noch aus.
- Kein verbundener Browser für visuelle Prüfung verfügbar. HTML-Ausgabe und
  Formularabläufe werden über den Anwendungstestclient geprüft.
- Railway-CLI meldet fehlende Anmeldung. Region, aktive Secrets, Vertragsbezug,
  Worker-Deployment und produktive Wirksamkeit wurden damit nicht bestätigt.
  Der vorhandene Vermerk zu us-west2 bleibt ein zu bestätigender Arbeitsstand.
- Keine produktiven Kundendaten exportiert oder gelöscht; kein Deployment und
  kein Vertragsabschluss durch diese Vorbereitung.

Quellen: [DSGVO](https://eur-lex.europa.eu/eli/reg/2016/679/oj?locale=de),
[§ 5 DDG](https://www.gesetze-im-internet.de/ddg/__5.html),
[§ 25 TDDDG](https://www.gesetze-im-internet.de/ttdsg/__25.html),
[BayLDA-Muster](https://www.lda.bayern.de/de/muster.html).
