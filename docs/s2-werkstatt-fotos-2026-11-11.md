# S2 – Werkstattbilder für die Startseite

Stand: 11. November 2026. Veröffentlicht nach ausdrücklichem Nutzerauftrag.

Auf Wunsch des Nutzers übertragen zwei neue Motive die warme Bildsprache der
Canva-Präsentation auf die bestehende Website. Das Einstiegsbild zeigt eine
fiktive Werkstattperson am Laptop. Die begleitende Sektion erhält eine fiktive
Mitarbeiterin mit Smartphone neben einem Fahrzeug. Beide Szenen sind sichtbar
als „KI-generiertes Symbolbild“ gekennzeichnet; sie zeigen weder das tatsächliche
Team noch einen Kundenbetrieb. Keine Bilder aus Canva kopiert.

Erzeugung: eingebautes ImageGen-Werkzeug. Keine API- oder CLI-Ausführung.
Die WebP-Dateien liegen unter `static/arbeitsplatz/startseite/`:

- `werkstatt-laptop-v1.webp`, 1536 × 1024, 147.740 Bytes
- `werkstatt-laptop-v1-768.webp`, 768 × 512, 55.302 Bytes
- `werkstatt-mobil-v1.webp`, 1536 × 1024, 111.354 Bytes
- `werkstatt-mobil-v1-768.webp`, 768 × 512, 44.710 Bytes

Die Optimierung änderte nur Größe und Kodierung. Der Browser wählt über srcset
eine passende Auflösung; das zweite Motiv wird verzögert geladen.

## Motivvorgaben

1. Fotorealistisches redaktionelles Bild eines Werkstattinhabers am Laptop an
   einem abgenutzten Holztisch, dunkle Arbeitskleidung, Notizbuch und Kaffeetasse.
   Glaubwürdige freie Kfz-Werkstatt, silbernes Auto und geordnete Werkzeuge im
   unscharfen Hintergrund. Warmes Fensterlicht, Creme, Waldgrün und Anthrazit.
   Querformat 3:2, natürliche Hände und Perspektive, keine Schrift, Logos oder
   erfundenen Bildschirmoberflächen. Fiktive illustrative Szene.
2. Fotorealistisches redaktionelles Bild einer Werkstattmitarbeiterin mit
   Smartphone neben einem stehenden silbernen Auto. Dunkle Arbeitsjacke,
   zusammengebundene Haare, ruhiger konzentrierter Ausdruck. Person im rechten
   Bilddrittel, Werkstatttiefe links, warmes Licht und grüne Werkzeugschränke.
   Querformat 3:2, keine lesbare Anzeige, Schrift, Logos oder zusätzlichen Personen.
   Fiktive illustrative Szene.

## Prüfung

- Jinja-Vorlage gerendert; Bilddateien und eigenständiger HTML-Export geprüft.
- Browser bei 1440 px: beide Bilder geladen, Kadrierung geprüft, kein horizontaler Überlauf.
- Browser bei 390 px: Einstiegsbild geladen, einspaltige Darstellung ohne horizontalen Überlauf.
- Beispielanfrage „Markus · Škoda Octavia“ erfolgreich umgeschaltet.
- `git diff --check` ohne Fehler. Keine neuen Tests für diese reine Bild-/Layoutänderung.
- Isolierter Vorschauserver ohne Datenbank oder Versandzugänge verwendet.

Privater dauerhafter Vorschau-Export: `artifacts/WerkSora-Startseite-Fotovorschau.html`.
Die Produktdemo, Preise, Kontaktziele und Anwendungsfunktionen bleiben vorhanden.
Der bisherige Einstiegs-Ticketblock wird durch das Foto ersetzt; die interaktive
Ticketdarstellung bleibt im Produktabschnitt.

## Figma-Verfeinerung

Der Nutzer hat anschließend die Verfeinerung in Figma beauftragt. Bestehende
Ansichten im selben Dokument aktualisiert:

- [Desktop, 1440 px](https://www.figma.com/design/Lah6WK5TUcrf3fLHFmexff?node-id=34-12)
- [Mobil, 390 px](https://www.figma.com/design/Lah6WK5TUcrf3fLHFmexff?node-id=34-13)

WerkSora-Wortmarke und Produkttexte vereinheitlicht; vorhandene Manrope-Schrift,
Farbvariablen und Button-Instanzen wiederverwendet. Die beiden Original-PNGs
als diskrete Bildfüllungen eingefügt, inklusive angepasster Kadrierung und
Symbolbildkennzeichnung. WebP-Füllungen waren im Figma-Renderer unsichtbar und
wurden durch PNG ersetzt; die Website behält ihre optimierten WebP-Dateien.
H1-Zeilen gruppiert, überbreite FAQ repariert, Einrichtungsbereich in Foto und
Text mit drei sichtbaren Schritten aufgeteilt. Die mobile Produktvorschau zeigt
jetzt zusätzlich das editierbare Ticket mit Fahrzeug, Anliegen und nächstem Schritt.
Preise und Kontaktadresse unverändert; Datenschutzrechte-Link in der Fußzeile ergänzt.

Visuelle Prüfung beider Gesamtansichten und betroffener Abschnitte abgeschlossen.
Strukturprüfung: keine Kinder außerhalb der Container; 112 editierbare Texte auf
Desktop, 107 auf Mobil, je fünf bestehende Button-Instanzen. Rasterbilder sind
nur die zwei Werkstattfotos und das Fahrzeugmotiv. Kein vollständiges UI-Raster.
Figma-Session: `5634074f-1b2a-4a3d-8d07-29c5a46576ad`.
Die zusätzlichen Figma-Verfeinerungen wurden anschließend auf ausdrücklichen
Wunsch in den Website-Code übernommen. Bildformate und Kadrierung, engere
H1-Zeilen, mobile Ticketabstände und Statusdarstellung entsprechen dem Entwurf.
Die mobile Schriftgröße passt sich schmaleren nutzbaren Breiten an, damit
„Mehr Werkstatt.“ auch mit sichtbarer Browser-Scrollleiste zusammenbleibt.
Bestehende Jinja-Makros, Farbvariablen, Schrift und Bildassets wurden wiederverwendet.

Abnahme vor Veröffentlichung: Desktop 1440 px, Mobil 390 px und Überlaufprüfung
bei 320 px bestanden. Beide Fotos geladen; Markus-Beispiel aktualisiert Fahrzeug,
Anliegen und nächsten Schritt korrekt. Drei bestehende Tests für öffentliches
Rendern, Sicherheitsheader/Nonce und statische Asset-Isolation bestanden.
Der erste Sandbox-Lauf scheiterte an lokalem SQLite-/HTTP-Zugriff; der isolierte
Testlauf mit freigegebenen lokalen Prozessrechten war erfolgreich.

## Veröffentlichung

[PR #10](https://github.com/WerkstattAI/WerkstattAI/pull/10) veröffentlicht den
geprüften Quellstand als `40a8cf4bde8cbfc198a697c6a8ae390752bd15a3`.
Die bestehende Railway-Quellbranch `codex/kundenkommunikation-2026-09-26`
wurde ohne Force auf diesen Stand vorgezogen. Keine Änderung an Railway-
Konfiguration, Datenbank oder Zugangsdaten. Windows blockierte die lokale
Railway-CLI; Veröffentlichung über die bereits aktive GitHub-Anbindung.
Das Railway-Panel bestätigte Deployment `7fdc35f2-20b3-4fbb-811c-decd6c95e30e`
als ACTIVE / Deployment successful. Die öffentliche Seite liefert die neuen
Fotos und `startseite.css?v=20261111-figma`.

Bei der Live-Endkontrolle wurde ein fehlendes Leerzeichen hinter dem auf Mobil
ausgeblendeten Zeilenumbruch in „Noch eine Frage?“ festgestellt und ergänzt.
