# Demo und Produktivkonto

`DEFAULT_WORKSHOP_ID` bezeichnet das bestehende Produktivkonto. Die historisch
verwendete ID `demo-werkstatt` bleibt erhalten: Tickets, Benutzer, Sitzungen und
WhatsApp-Zuordnungen werden weder verschoben noch gelöscht.

`DEMO_WORKSHOP_ID` bezeichnet ausschließlich die öffentliche Demo und ist
standardmäßig `werkstattai-demo`. Die beiden IDs müssen unterschiedlich sein.
Die Demo wird als eigener Mandant mit `is_demo = 1`, Beispieldaten und aktivem
Zugang angelegt. Sie hat weder einen Benutzer noch eine WhatsApp-Nummer und
erscheint nicht in der Verwaltung der Produktivkonten. Eine bestehende
Produktivwerkstatt kann nicht durch diese Konfiguration zur Demo werden.

- `/assistant` öffnet die Demo. Auch `/chat` ohne Werkstatt-ID nutzt die Demo.
- `/assistant?workshop_id=…` öffnet den Kundenchat der angegebenen Werkstatt.
  Der passende Link steht unter **Einstellungen → Kundenchat öffnen**.
- Demo und Produktivkonto speichern Tickets und Sitzungen unter getrennten
  Werkstatt-IDs. Bestehende Kundenzugänge behalten ihre bisherige Zuordnung.
- Fehlende oder bewusst geleerte Profilfelder werden nicht durch Beispieldaten
  ergänzt. Der Assistent weist auf fehlende Angaben hin.

## Verhalten beim Start

Die Initialisierung legt fehlende Tabellen, Spalten und Startkonten an. Bereits
gespeicherte Profile, Abodaten, WhatsApp-Konfigurationen und Benutzer werden
nicht zurückgesetzt. `DASHBOARD_ADMIN_*`, `WHATSAPP_DEFAULT_PHONE_NUMBER_ID` und
`TRIAL_DAYS` dienen beim Anlegen neuer Startkonten als Vorgaben. Spätere Änderungen
erfolgen über die Werkstattverwaltung; Passwortänderungen bestehender Konten
über die dortige Funktion zum Zurücksetzen des Passworts.

Ein neues Produktivkonto beginnt mit dem Namen „Meine Werkstatt“ und leeren
Kontaktdaten. Beispieldaten gehören nur zum separaten Demobereich.

## Bestehende Daten

Frühere Versionen haben das Standardprofil bei jedem Start überschrieben und
öffentliche Demoanfragen im selben Konto gespeichert. Bereits überschriebene
Profilwerte lassen sich ohne Sicherung nicht rekonstruieren. Vorhandene
Datensätze werden deshalb nicht automatisch bereinigt: Frühere Testtickets
sind nicht zuverlässig von echten Anfragen zu unterscheiden. Eindeutig
identifizierte Testtickets können anschließend gezielt archiviert werden.
