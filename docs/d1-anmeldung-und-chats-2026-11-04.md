# D1 – Anmeldung, WhatsApp und Kundenchat

## Ergebnis und Umfang

Die drei Ansichten übernehmen das freigegebene Erscheinungsbild von Dashboard
und Ticket: Inter, dunkle Markenzeile, grüne Hauptaktionen, ruhige weiße Flächen
und helle Gesprächsblasen. Schrift, Farbtokens und Navigation liegen gemeinsam
in `static/arbeitsplatz/grundlagen.css`; die seitenbezogenen Regeln sind getrennt.
Dashboard und Ticket beziehen denselben unveränderten Navigationsstil ein.

Die WhatsApp-Ansicht verwendet die vorhandene horizontale Hauptnavigation mit
korrekt aktivem Eintrag. Kontakte erscheinen als getrennte Karten, der Verlauf
als Gespräch. Diagnose und Testversand bleiben vollständig vorhanden und stehen
auch ohne JavaScript hinter dem Gespräch. Beim Wechsel zwischen Assistent und
Werkstatt aktualisieren sich Gesprächskopf und Kontaktliste gemeinsam; Entwurf,
Nachrichtenzweck und ausgewählte Kundenfrage bleiben erhalten.

Im Kundenchat steht das Gespräch vor der Hilfe, auch in der Lesereihenfolge und
auf dem Telefon. Die Anmeldung behält ihr einfaches Formular und erhält die
gemeinsame Gestaltung. Es wurden keine neuen Login-Funktionen versprochen oder
unwirksame Schaltflächen ergänzt.

## Erhaltene Verträge

- Anmeldung: POST-Ziel, E-Mail/Passwort, `next`, Autofill, Pflichtfelder,
  Fehleranzeige, Datenschutzlinks und bestehende serverseitige Authentifizierung.
- WhatsApp: Werkstatt-/Kontaktauswahl, aktive Tickets, Medien, Autoren,
  Nachrichtenbezug, echte Versandstatus, Übernahme, gezielte Antworten,
  Versandklärung, Entwurfswiederherstellung, manuelles Öffnen, Startvorlagen,
  Kundendienstfenster, Verbindungsdiagnose und Testformular.
- Kundenchat: bestehende Sitzungsschlüssel, Aufnahmeablauf, Schnellaktionen,
  Formular- und Polling-IDs, Zeichengrenze, Tastaturbedienung, Laden/Fehler,
  Neustart, Gesprächsstatus sowie Datenschutz-/Demohinweise.
- Rechteabhängige Admin-Navigation und POST-Abmeldung; bestehende Dashboard-
  und Archivmarkierung bleiben erhalten.

Das Kundenchat-Skript ist gegenüber dem Ausgangsstand bytegleich. Das
WhatsApp-Skript ist bis auf das entfallene Verschieben der Diagnose im DOM
unverändert. Die zusätzliche Statusaktualisierung liegt im gemeinsamen
Dashboard-Skript. Keine Änderung an Geschäftslogik, Versanddiensten, Datenbank,
Sicherheitsmiddleware oder Coexistence.

## Nachweise

Vollständiger Python-Lauf: 770 Fälle in 827,886 Sekunden ohne Fehler; davon
90 PostgreSQL-Fälle mangels isolierter Testdatenbank übersprungen, also
680 tatsächlich bestanden. JavaScript: 62/62 bestanden. Drei neue
Integrationstests prüfen Login-Vertrag, öffentliche Chatbedienung sowie
WhatsApp-Formulare, Fragebezug und aktive Navigation. Auch die bisherigen
Dashboard-/Tickettests bleiben erfolgreich. `git diff --check` ohne Befund.

Lokale Browserprüfung ausschließlich mit erfundenen Daten und ohne
Versandzugänge: erfolgreicher und fehlgeschlagener Login; Nachrichtenaufnahme
im Kundenchat, Antwort, Sitzungsfortsetzung und Neustart; Auswahl einer offenen
Kundenfrage, gesperrter Versand ohne Einrichtung, Übernahme in beide Richtungen,
gleichzeitige Statusanzeige und unveränderter Entwurf. Diagnose erreichbar.
Desktop sowie Telefonbreite 390 px geprüft; die nutzbare Breite der Chatseiten
beträgt wegen der Browser-Scrollleiste 375 px, ohne Seitenüberlauf.

Die Fortsetzung einer laufenden Aufnahmesitzung bedeutet keine neue Funktion
zum vollständigen Wiederanzeigen aller bisherigen Aufnahmeblasen nach Reload.
Der bestehende Wiederherstellungsablauf bleibt unverändert.

Private Screenshots und Protokolle bleiben im ignorierten `artifacts/`-Ordner;
sie werden nicht mit Git oder Docker veröffentlicht. Kein echter Versand und
keine Änderung produktiver Kundendaten während der Prüfung.

## Veröffentlichung und Restumfang

Ausgangspunkt: `9cdbf950b474184b26e81b4611cf483755bdb808` (Dashboard/Ticket, PR #2).
Folgezweig: `codex/d1-login-chats-2026-11-04`. Tatsächlichen Merge, aktiven
Railway-SHA und Produktionskontrolle getrennt im PR und in Notion dokumentieren.
Der bestehende Railway-Quellzweig bleibt erhalten. Bei Bedarf normaler Revert
des UI-Commits; keine Datenbankwiederherstellung für diese Änderung erforderlich.

Dieser Schritt umfasst die drei beauftragten Seiten. Direktannahme,
WhatsApp-Verbindungsassistent, Einstellungen, Abo und Admin wurden nicht neu
gestaltet. Die zugehörigen Einstiege und Funktionen bleiben vorhanden. D1 ist
deshalb nicht automatisch als vollständige Neugestaltung sämtlicher
Verwaltungsseiten abgeschlossen; nächster Schritt ist der gemeinsame
visuelle Abgleich und die Entscheidung über verbleibende D1-Ansichten.
