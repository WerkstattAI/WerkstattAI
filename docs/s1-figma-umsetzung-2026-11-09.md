# S1 – Figma-Entwurf als öffentliche Startseite

Der Nutzer hat die Veröffentlichung am 9. November 2026 beauftragt.
Vorlage: https://www.figma.com/design/Lah6WK5TUcrf3fLHFmexff?node-id=34-12

- Helle Manrope-Typografie, grüne Akzente, Nachricht-zu-Ticket-Komposition,
  Produktvorschau, Ablauf, freigegebene Preise, Einrichtung, FAQ und Kontakt.
- Figma-Grafiken und Manrope einschließlich OFL-Lizenz lokal ausgeliefert.
- Semantische Jinja-Makros und responsives CSS statt fest positionierter Exportflächen.
- Drei fiktive Anfragen lassen sich auswählen. Das Golf-Symbolbild wird nur beim
  passenden Beispiel gezeigt. Mobil bleibt die ausgewählte Detailansicht zugänglich.
- Demo öffnet den vorhandenen getrennten Assistenten. Kontakt öffnet eine E-Mail;
  es gibt keinen direkten Aboabschluss. Bestehende Rechts- und Loginlinks bleiben.
- Preise: 149 €/Monat, 299 € Einrichtung; erste drei Pilotwerkstätten erhalten
  drei bezahlte Monate für 99 €/Monat. Meta zusätzlich. Steuerliche Behandlung und
  Gesamtpreis werden weiterhin im persönlichen Angebot ausgewiesen.

## Prüfung

- Bestehender öffentlicher Render-Test bestanden. Windows meldete beim anschließenden
  Aufräumen eines temporären Testordners einen Berechtigungsfehler; Test selbst erfolgreich.
- Browser: Desktop und 390-px-Mobilansicht ohne horizontalen Überlauf.
- Alle vier Bildverwendungen geladen, Manrope geladen.
- Inspektionsbeispiel zeigt Markus/Octavia und den passenden nächsten Schritt.
- Demo-Link öffnet den bestehenden Demo-Assistenten.
- Keine Änderungen an Dashboard, WhatsApp-Integration, Datenbank oder Abonnementlogik.

Die bereits dokumentierten offenen Angaben zu Anbieter, Steuern und Pilotbedingungen
werden durch dieses gestalterische Deployment nicht als erledigt markiert.
