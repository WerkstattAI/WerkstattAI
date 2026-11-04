# D1 – Feinschliff von Verwaltung, Ticketkarten und Kommunikation

## Ergebnis

Direktannahme, Einstellungen, Abonnement, Adminliste/-bearbeitung und
WhatsApp-Verbindungsassistent nutzen nun den gemeinsamen Kopf und dieselben
Farben, Schriften, Formularflächen und mobilen Abstände. Bestehende Formulare,
Routen, Rechte und Verbindungsaktionen bleiben erhalten. Das Abo zeigt das
Enddatum im vorhandenen Anzeigeformat statt als technischen ISO-Zeitstempel.

Freie Flächen einer Ticketkarte öffnen das zugehörige Ticket mit Rückkehrkontext.
Links, Telefonnummern, Vorschau, Aktionen, Formulare und Textauswahl behalten
ihre eigene Funktion. Die vier Hauptkennzahlen erhalten passende Symbole,
ruhige Farbtöne und eine klarere Hierarchie; Zählung und Filterziele ändern sich
nicht.

Das gemeinsame Golf-Bild wurde durch lokale SVG-Symbole für Kompaktwagen,
Limousine, Kombi, SUV, Transporter, Coupé und ein neutrales Fahrzeug ersetzt.
Explizite Karosserieangaben haben Vorrang; einige bekannte Modellfamilien werden
zugeordnet, unbekannte Angaben bleiben neutral. Diese Heuristik ist keine
Fahrzeugdatenbank und bestimmt weder Baureihe noch genaue Karosserie sicher.
Die Darstellung ist ausdrücklich als „keine exakte Modellabbildung“ bezeichnet.
Keine externen Bilddienste, kostenpflichtigen Angebote oder neuen Datenfelder.

## Einfacher schreiben und Bilder öffnen

Ticketgespräche erhalten ruhigere Nachrichtenblasen und einen kompakten Editor.
Normale Nachrichten starten als `workshop_notification`, ohne verpflichtende
Zweckauswahl. Sie schließen keine Kundenfragen. „Antworten“ an einer offenen
Frage wählt bewusst `workshop_answer` und die stabile Nachrichten-ID aus;
Nachrichtenoptionen enthalten weiterhin Rückfragen und gezielte Antworten.
Veraltete Antwortentwürfe werden niemals still zu normalen Nachrichten.
Duplikatschutz, Versandklärung, Entwurfserhalt, 24-Stunden-Fenster und
serverseitige Validierung bleiben aktiv. Die technischen Versandhinweise sind
im Ticket aufklappbar; bei Versandblockaden sind sie direkt geöffnet.

Empfangene Bilder öffnen in einem zugriffsgeschützten Dialog mit Original-Link,
Escape-Schließen und Fokusrückgabe. Nicht verfügbare Bilder haben einen
verständlichen Fehlerzustand statt eines kaputten Vorschaubilds. Externe
Skripte tragen den bestehenden CSP-Nonce. Medienzugriff und Isolation der
Werkstätten bleiben unverändert; es werden keine Medien öffentlich gespeichert.

**Grenze:** Dies stellt keine bei Meta fehlenden Dateien wieder her und ergänzt
keinen ausgehenden Foto-Upload. Der gemeldete konkrete Produktionsfehler muss
nach Anmeldung anhand des Original-Links untersucht werden. Beim heutigen
Versuch zeigte die Produktionskarte das Login; kein Fehlergrund wurde geraten.

## Prüfung

- 54 gezielte Python-Tests bestanden: UI-Verträge, Verwaltung, CSP-Nonce,
  Nachrichten, Symbolzuordnung, Medien und Dashboard-Workflow; keine übersprungen.
- Alle 64 JavaScript-Tests bestanden, einschließlich normalem Nachrichtenstart
  und blockierter Umdeutung veralteter Antwortentwürfe. Kein neuer vollständiger
  Python-/PostgreSQL-Lauf behauptet.
- Lokale Browserkontrolle auf erfundenen Daten: Direktannahme, Einstellungen,
  Abo, Adminliste und Kontobearbeitung; Öffnen per Fahrzeugtext; normale
  Webchat-Nachricht ohne Zweckauswahl lässt die Frage offen; gezielte Antwort
  schließt genau diese Frage. Erfolgreicher Bilddialog, Escape/Fokusrückgabe und
  Fehlerzustand mit zwei ausschließlich lokalen Medienproben geprüft.
- Dashboard, Ticket und Einstellungen bei Telefonbreite 390 px kontrolliert.
  Hauptnavigation scrollt horizontal innerhalb ihrer eigenen Leiste.
- `git diff --check` sauber. Private Proben, Bilddateien und Logs unter
  `artifacts/` bleiben außerhalb von Git und Docker. Kein echter WhatsApp-Versand.

Die ersten Tests scheiterten an der Sandbox-Berechtigung für temporäres SQLite;
der gezielte Lauf außerhalb dieser Einschränkung bestand. Zwei alte
Template-Erwartungen an einen leeren Nachrichtentyp wurden an den ausdrücklich
gewünschten Nachrichtenstandard angepasst. Die Browserprüfung deckte außerdem
fehlende Nonces an den neuen Skripten auf; diese sind korrigiert und getestet.

## Veröffentlichung und nächster Schritt

Ausgang: `9ad469a40532ff95d57d1ddd8d328b6f84fbffbe`.
Zweig: `codex/d1-feinschliff-2026-11-04`.
Merge und aktives Deployment werden im PR und in Notion separat dokumentiert.
Keine Migration, keine Änderung der Railway-Quelle oder Coexistence.
Nächster Schritt: gemeldeten Bildfehler nach Login konkret prüfen und Mikołajs
visuelle Rückmeldung zu den Symbolen und neuen Ansichten aufnehmen.
