# S1 – Helle Produktseite

Stand: 8. November 2026. Lokaler Entwurf, noch nicht veröffentlicht.

## Umsetzung

- Nutzerwahl: hell und professionell. Graphitfarbene Typografie, grüne Akzente,
  ruhige Flächen und großzügiger Produkteinblick.
- Neuer Einstieg: „Kundenanfragen im Griff. Kopf frei für die Werkstatt.“
- Tatsächlicher Dashboard-Ausschnitt aus dem lokalen Testbetrieb mit erfundenen
  Kunden, Telefonnummern und Fahrzeugdaten. Screenshot unverändert als Produktbild
  verwendet, öffentlich nur dieses freigegebene Beispielmaterial, keine Live-Daten.
- Drei umschaltbare Anfragen erklären den Weg vom Anliegen zum Ticket. Demo-Link
  öffnet den vorhandenen, getrennten Demobereich. Kontakt bleibt eine E-Mail-Anfrage.
- Freigegebene Preise: 149 €/Monat, 299 € Einrichtung; erste drei Pilotwerkstätten
  für die ersten drei bezahlten Monate 99 €/Monat, anschließend 149 €. Meta separat.
  FAQ nennt 398 € für den ersten bezahlten Pilotmonat inklusive Einrichtung,
  vor Steuer und Meta. Preiskennzeichnung vor Veröffentlichung endgültig festlegen.
- Keine unbelegte kostenlose Testphase, kein unbegrenzter Nachrichtentarif,
  keine Telefonannahme oder verbindliche automatische Terminbuchung zugesagt.
- Startseiten-CSS liegt getrennt im bereits eingebundenen statischen Verzeichnis;
  Startseite und Login verwenden relative Links für lokale und produktive Umgebung.

## Prüfung

- Bestehender Python-Test für öffentliches Rendern der Startseite bestanden.
- Browser bei 1280 px: Produktbild geladen, keine horizontale Überbreite,
  Inspektions- und Bremsenbeispiel umgeschaltet, Preis-FAQ geöffnet,
  Einstieg in den vorhandenen Demo-Chat erfolgreich.
- Browser bei 390 px: Einspaltige Darstellung und Preiskarte visuell geprüft,
  kein horizontaler Überlauf (Dokumentbreite 375 px bei 390 px Fensterbreite),
  keine defekten Bilder; Inspektionsbeispiel funktioniert.
- Kontaktadressen kontrolliert, keine E-Mail und keine WhatsApp-Nachricht versendet.
- Lokale Screenshots unter `artifacts/s1-*.png` bleiben außerhalb von Git.

## Nächster Schritt

Mit dem Nutzer den lokalen Entwurf ansehen. Endgültige Marke/Domäne und
steuerliche Preiskennzeichnung vor öffentlicher Veröffentlichung bestätigen.
Detailbedingungen sowie technisches Abonnementende bleiben in C1 offen.
Kein Deployment, keine Zahlungsintegration und keine Änderung am Dashboard.
