# Ticketoberfläche: gezielter Feinschliff, 13. November 2026

Die kleinen aufklappbaren Kennzahlen und Aufgabenvorschläge wurden durch direkte
Ticketansichten ersetzt. Alle Tickets, Jetzt bearbeiten, Wartet auf Kunden und
Erledigt stehen mit Zählern über derselben Liste. Notfälle, Kundeninformationen
und Kostenvoranschläge bleiben im Menü Weitere Ansichten erreichbar. Die vier
Hauptkennzahlen filtern weiterhin die Liste und markieren die aktive Auswahl.
Bestehende Filtersemantik, globale Zählung und Werkstattabgrenzung bleiben erhalten.

Wiederholte grüne Nachrichtenverweise entfallen aus den Listenkarten. Die letzte
Nachricht, offene Fragen, Gesprächsstatus und der vollständige Verlauf im Ticket
bleiben erreichbar. Die Suche erhält ein Symbol, 16 px Eingabetext und 48 px Höhe.
Filter haben einen sichtbaren Auslöser und öffnen sich beim Ansichtswechsel nicht
mehr automatisch. Im Ticket wird der Status über drei native Radiofelder mit
explizitem Speichern gewählt. Der Rückweg zur Liste ist ein neutraler Pfeilknopf.
Schnellstatus, Fokus und Kontrast wurden im selben Gestaltungssystem vereinheitlicht.

## Gestaltungsgrundlage

Taste Skill 2.5.1: neutrale Flächen, bestehende grüne Markenfarbe, konsistente
Abstände, lesbare Beschriftungen, sichtbarer Fokus, ruhige Rückmeldung bei Hover.
Die bestehende Anwendung bleibt eine Arbeitsoberfläche. Kein neues Farbschema,
keine Marketinganimationen und keine neue Bildsprache. Texte bleiben sachlich,
deutsch und auf eine Handlung bezogen. Keine neuen Abhängigkeiten oder Bilder.

Referenzen für direkte Ansichten über einer gemeinsamen Liste:
[Linear: Filter](https://linear.app/docs/filters) und
[Intercom: Ansichten](https://www.intercom.com/help/en/articles/6588834-organize-your-inbox-with-custom-views-and-folders).
Es wurden weder Gestaltungsmittel noch Code dieser Anbieter kopiert.

## Prüfung

- 30 bestehende Python-Tests zu Dashboard, Formularen und Kommunikation bestanden.
- Fünf JavaScript-Tests des Aktualisierungsfeeds bestanden.
- Lokale Browserprobe mit erfundenen Tickets: alle elf Ansichten, Suche,
  Statuswechsel mit Zähleraktualisierung, Statusformular einschließlich simuliertem
  Serverfehler, Erhalt der Auswahl und Rückkehr in den bisherigen Listenkontext.
- Escape, Klick außerhalb und Fokus des Ansichtenmenüs auch nach Listenaktualisierung.
- Kein horizontaler Seitenüberlauf bei 1440, 1024, 820, 768, 390 und 320 px;
  keine JavaScript-Laufzeitfehler in der Bedienprobe.
- Taste-Skill-Screenshots von Dashboard und Ticket; Kontrast- und Fokusbefunde
  wurden nachgebessert. Lokale Nachweise liegen ausschließlich unter artifacts/.

Der allgemeine Taste-Checker bewertet auch diese Arbeitsoberfläche nach seinen
Landingpage-Regeln: bildschirmhoher Einstieg, eine Sektion pro Bildschirm,
Marketingbilder und Animationen. Diese Anforderungen passen nicht zum beauftragten
kleinen Dashboard-Feinschliff. Auch gescrollte, abgeschnittene Listeneinträge werden
als Überlagerung des danebenliegenden Vorschaufensters bewertet. Diese Befunde
werden nicht durch einen Umbau der Arbeitsoberfläche oder Eingriffe in den Checker
verdeckt. Ein vollständiger Taste-Gate-PASS wird daher nicht behauptet.

Keine produktiven Kundendaten oder Nachrichten wurden für die Prüfung verändert.
Die Homepage war nicht Gegenstand der konkret benannten Änderungen.
