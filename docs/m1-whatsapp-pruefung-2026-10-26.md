# M1: realer WhatsApp-Test vom 25./26. Oktober 2026

**Ergebnis: M1 abgeschlossen auf Grundlage der unten getrennt ausgewiesenen
technischen Prüfungen und Nutzerbestätigungen.** Die Testnummer wurde wieder
registriert; Versand, Eingang, manueller Betrieb und echter Bildabruf
funktionieren im beobachteten Ablauf. Die öffentliche GET-Verifikation bleibt
als eigener Fehler offen.

## Version und Umfang

- Anwendung: https://werkstattai-whatsapp.up.railway.app
- Während der Prüfung bestätigter Railway-Anwendungscommit:
  `aa965e481f62ad34ee752d5b3cd89f365c4d30fb`.
  Deployment `e81fee99-9838-4ee3-9639-ba2674b3537b`, Status `SUCCESS`.
  Der Versionsnachweis stammt aus Railway; kein Laufzeit-Dateivergleich.
- Zeitraum: 25. Oktober abends bis 26. Oktober 2026 nach Mitternacht,
  Zeitzone Europe/Berlin, MEZ (UTC+1).
- Ausschließlich der ausdrücklich bestätigte eigene Testkontakt und die
  bestehende Meta-Testnummer. Keine Nachrichten an andere Empfänger.
- Berichtsgrundlage: technischer Prüfstand
  `5e9f473cfa7df43faf795af71318984f3712a713`.
  Lokaler Ausgangsbranch und Remote stimmen überein; lokaler Arbeitsbaum sauber.
  Veröffentlichung als reine Dokumentation auf separatem Aufgabenbranch.
- Keine Änderung an Anwendungscode, Paketen, Railway-Variablen oder Deployment.
  Die ausdrücklich genehmigte Wiederregistrierung änderte den Meta-Nummernstatus.

## Fehler und Wiederherstellung

Der erste genehmigte einzelne Vorlagenversand wurde am 25. Oktober um
21:24:48 UTC mit HTTP 400 und Meta-Fehler **133010, Account not registered**
abgelehnt. Token, erlaubter Empfänger und Abonnement der richtigen App durch
das WhatsApp-Konto waren vorhanden.

Nach ausdrücklicher Freigabe wurde dieselbe Nummer über die Cloud API erneut
registriert: HTTP 200, `success=true`; danach `CONNECTED` und `CLOUD_API`.
Die Ursache der früheren Deregistrierung oder ein Ablauf der Testnummer wurde
nicht nachgewiesen. Ein anschließend genehmigter einzelner
`hello_world`-Versand war erfolgreich.

Der Registrierungs-PIN steht weder in diesem Bericht noch im Repository.
Meta meldete weiterhin `code_verification_status=NOT_VERIFIED` und
`is_pin_enabled=false`. Eine aktivierte Zwei-Schritt-Verifizierung wird
daher nicht behauptet.

## Ergebnisse mit Quelle und Grenze

| Prüfschritt | Ergebnis und Nachweis |
| --- | --- |
| Grundlegende Textannahme, Ticketanlage und automatische Antwort | Mikolaj bestätigte am 23. Oktober einen früheren realen Telefontest. Datum und Anwendungsversion dieses früheren Ablaufs sind nicht bekannt. Er wurde in dieser Sitzung nicht neu aufgebaut. |
| Vorlagenversand nach Wiederregistrierung | Graph API HTTP 200; echte Webhook-Statusereignisse `sent`, `delivered` und `read`. Empfang zusätzlich am Telefon durch Mikolaj bestätigt. Dies ist kein neuer automatischer Assistententest. |
| Neuer Texteingang | Am 25. Oktober um 21:36:57 UTC / 22:36:57 MEZ einmal gespeichert, Verarbeitung vollständig, richtigem bestehenden Ticket zugeordnet. Der Text wich vom vorgeschlagenen Marker ab; geprüft wurde der einzige neue Eingang des bestätigten Kontakts nach der Registrierung. |
| Manueller Betrieb | Die zuvor bereits übernommene Unterhaltung blieb `manual` / `waiting_for_workshop`. Nach dem neuen Texteingang während 75 Sekunden Beobachtung null automatische Antworten. Der Übernahme-Klick und der Wechsel aus dem Assistentenmodus wurden diesmal nicht erneut ausgeführt. |
| Manuelle Antwort über die Anwendung | Am 25. Oktober um 21:50:51 UTC / 22:50:51 MEZ genau eine genehmigte Antwort über das normale Dashboard-Antwortformular per HTTP: HTTP 200, Anwendungsstatus `sent`, genau ein Datensatz, Rolle `workshop`, Zweck `workshop_notification`, richtiges Ticket, `delivered`, `dispatch_state=complete`. Mikolaj bestätigte den Empfang am Telefon. Kein Browser-Klicktest. |
| Echtes Foto | Eingang am 25. Oktober um 23:04:32 UTC / 26. Oktober 00:04:32 MEZ: genau ein Bilddatensatz, Verarbeitung vollständig, richtigem Ticket zugeordnet. Ein tatsächlich vom Nutzer gesendetes Foto wurde verwendet; das vorbereitete synthetische Bild wurde nicht verwendet. |
| Geschützter Meta-Bildabruf | Nicht angemeldet wird die Anmeldung verlangt. Angemeldet liefert der Anwendungsendpunkt HTTP 200, `image/jpeg`, 128253 Bytes und `Cache-Control: no-store`. Die tatsächlich abgerufene JPEG-Datei wurde lokal dekodiert und angesehen. |
| Anzeige im Posteingang und Ticket | Beide angemeldeten Seiten HTTP 200 mit Bildverweis. Mikolaj bestätigte anschließend ausdrücklich die sichtbare Darstellung in beiden Ansichten seiner angemeldeten Sitzung. Die unabhängige technische Prüfung umfasste HTTP, HTML-Verweise und Bilddatei; die Browserdarstellung ist durch den Nutzer bestätigt. |
| Duplikate im beobachteten Ablauf | Je ein Datensatz für den neuen Text, das Bild und die manuelle Antwort; Zuordnung zum bestehenden Ticket. Kein künstlicher Webhook-Replay, kein neuer Ticketanlage- oder Lasttest in Produktion. |

Bildprüfung um `2026-10-25T23:04:42Z`.
SHA-256 der abgerufenen Datei:
`030dc336b03e98ddb26b2fba9e10f9e8d6506e65376b34c769db7d1fce216c32`.
Das Foto selbst sowie Empfänger-, Sitzungs- und Zugangsdaten werden nicht veröffentlicht.

## Offener Fehler: öffentliche GET-Verifikation

Mit dem vorhandenen Verify-Token lieferte das Backend `/meta/whatsapp`
HTTP 200 und die unveränderte Challenge. Der konfigurierte öffentliche
Cloudflare-Callback lieferte dagegen **HTTP 403**.

Die derzeitige POST-Weiterleitung funktioniert: echte Zustellereignisse,
Text und Bild kamen an. Daraus folgt keine korrekte erneute GET-Verifikation.
An dieser Konfiguration wurde nichts geändert. Vor einer erneuten
Webhook-Einrichtung oder Werkstattanbindung muss die Abweichung untersucht werden.

## Einordnung und Fortsetzung

M1 wird mit dem früher vom Nutzer bestätigten Grundablauf und den jetzigen
ergänzenden Nachweisen geschlossen. Das ist kein vollständig neuer Durchlauf
aller Schritte auf einem frischen Kontakt. Die Grenzen je Schritt sind oben
festgehalten. Der vorherige Bericht bleibt als
[historische Vorprüfung](m1-whatsapp-pruefung-2026-10-21.md) erhalten.

Es wurden keine weiteren Testnachrichten versendet und keine automatisierten
Testreihen wiederholt. Die 26 lokalen Tests vom 21. Oktober sind historische,
simulierte Ergebnisse. Für diese Dokumentationsänderung werden Inhalt,
Änderungsumfang und Ausschluss privater Daten geprüft.

**Nächster Schritt: M2 vorbereiten.** Erforderlichen Autorisierungs- und
Embedded-Signup-/Coexistence-Ablauf mit aktuellem Code und Meta-Zugang abgleichen;
den GET-403-Befund dabei als offene technische Voraussetzung aufnehmen.
Coexistence, externe Werkstattnummern und Pilotbereitschaft sind durch M1
nicht bestätigt.

Bereinigte lokale Protokolle und private Prüfarbeitsdateien liegen getrennt
vom Produkt-Repository im lokalen Verzeichnis
`whatsapp-pruefung-2026-10-25`. Sie sind nicht Teil dieses Commits.
