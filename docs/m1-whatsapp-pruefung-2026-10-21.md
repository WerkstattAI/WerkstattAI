# M1: tatsächlicher WhatsApp-Ablauf – Vorprüfung vom 21. Oktober 2026

**Ergebnis: offen; echter Ablauf noch nicht geprüft.** Mikolaj nimmt später
mit dem eigenen Telefon teil und hat zunächst die unabhängigen Prüfungen
beauftragt. Es wurde kein Produktfehler nachgewiesen.

## Version und Ausgangspunkt

- Prüfdatum: 21. Oktober 2026, Zugangscheck ab 00:41 Uhr MESZ
  (`2026-10-20T22:41:23Z`).
- Repository: [WerkstattAI/WerkstattAI](https://github.com/WerkstattAI/WerkstattAI).
  Ausgangsbranch: `codex/kundenkommunikation-2026-09-26`;
  lokaler Prüfcommit: `4e8b9799ded93a4c6d91711fbdc5427988d15847`.
  Arbeitsverzeichnis zu Beginn sauber.
- Aktueller Remote-Nachweis: `git ls-remote origin
  refs/heads/codex/kundenkommunikation-2026-09-26` lieferte
  `aa965e481f62ad34ee752d5b3cd89f365c4d30fb`.
  Die lokalen Dokumentationscommits `bd0a218` und `4e8b979` lagen darüber.
  Deshalb enthält der Remote-Projektstand noch den 26. September, die lokale
  Fassung bereits den 19. Oktober. Anwendung, Templates, Abhängigkeiten,
  Dockerfile und Cloudflare-Code unterscheiden sich zwischen diesen Commits nicht.
- Geprüfte Anwendung: https://werkstattai-whatsapp.up.railway.app.
  Railway meldet Deployment `e81fee99-9838-4ee3-9639-ba2674b3537b`,
  `SUCCESS`, Instanz `RUNNING`, Commit
  `aa965e481f62ad34ee752d5b3cd89f365c4d30fb`.
  Ein direkter Dateivergleich in der laufenden Instanz war mangels lokalem
  Railway-SSH-Schlüssel nicht möglich. Die Versionsangabe ist durch die aktuelle
  Anbieterabfrage belegt; ein Versionsendpunkt der Anwendung wurde nicht gefunden.
- Berichtsbranch: `codex/m1-whatsapp-pruefung-2026-10-21`, aufbauend auf dem
  lokalen Prüfcommit; die beiden bisherigen lokalen Commits bleiben erhalten.
  Kein Reset, Merge oder erzwungener Push.

## Ergebnisse und Nachweise

| Prüfschritt | Ergebnis | Nachweis und Grenze |
| --- | --- | --- |
| Anwendung erreichbar | bestanden | `/health`: HTTP 200, `ok=true`. |
| Dashboard-Anmeldung und Posteingang | bestanden | Anmeldung mit vorhandenem Zugang; anschließend Dashboard, Einstellungen und WhatsApp-Posteingang HTTP 200. Nur HTTP-Prüfung, keine neue visuelle Browserprüfung. |
| Werkstatt und `phone_number_id` | bestanden | Einstellungen der Standardwerkstatt `demo-werkstatt`: Nummern-ID vorhanden und identisch mit der Railway-Konfiguration. Der historische ID-Name bezeichnet laut Kontodokumentation das Produktivkonto, nicht die öffentliche Demo. Eine zusätzliche globale Eindeutigkeitsabfrage der Datenbank war über SSH nicht möglich. |
| Meta-Nummer und Zugriff | bestanden | Graph API `v23.0`: HTTP 200, `CONNECTED`, `LIVE`, `CLOUD_API`, `GREEN`; gültiger Systemnutzerzugang mit `whatsapp_business_messaging` und `whatsapp_business_management`. `code_verification_status=NOT_VERIFIED` wurde unverändert beobachtet; daraus folgt hier keine Aussage zur Unternehmensverifizierung oder Zustellung. |
| Webhook-Konfiguration und Verifikation | bestanden | Aktives App-Abonnement für `whatsapp_business_account` mit Feld `messages`, passende Callback-Adresse. Gültige GET-Challenge an öffentlichem Callback und `/meta/whatsapp` jeweils HTTP 200 und identischer Challenge-Text. Kein Produktions-POST erzeugt. |
| WhatsApp-Konto abonniert die App | nicht geprüft | Tokenabfrage lieferte keine granularen Kontoziele; daraus wurde kein Konto geraten. Das aktive App-Webhook-Abonnement allein belegt diese Kontozuordnung nicht. |
| Eigener Testempfänger und Freischaltung | nicht geprüft | Keine Eigentums-/Nummernbestätigung; Nutzerantwort: „Später; zunächst alle unabhängigen Prüfungen erledigen.“ Keine Nummer aus alten Logs verwendet. |
| a) Echter Texteingang über Meta und richtige Werkstatt | nicht geprüft | Keine neue Nachricht vom eigenen Telefon. |
| b) Annahme führt zu genau einem passenden Ticket | nicht geprüft | Noch kein echter Testlauf oder zugehöriges Ticket. |
| c) Automatische Antwort am Telefon empfangen | nicht geprüft | Weder API-Annahme noch Versandstatus oder Telefonempfang eines neuen Testversands liegen vor. |
| d) Mitarbeiterübernahme hält den Assistenten an | nicht geprüft | Übernahmeformular erreichbar; im echten Gespräch noch nicht betätigt. |
| e) Manuelle Dashboard-Antwort empfangen | nicht geprüft | Noch kein autorisierter eigener Empfänger und kein manueller Testversand. |
| f) Weitere Kundennachricht im manuellen Modus ohne Automatik | nicht geprüft | Erfordert die echte übernommene Unterhaltung. |
| g) Synthetisches Bild: Empfang, Vorschau im Posteingang/Ticket, Meta-Abruf | nicht geprüft | PNG vorbereitet, noch nicht über WhatsApp gesendet. Nicht angemeldeter Bildabruf leitet zur Anmeldung; angemeldeter Abruf einer nicht vorhandenen ID liefert 404. Das ist kein erfolgreicher Meta-Bilddownload. |
| h) Keine doppelten Nachrichten/Tickets im beobachteten Ablauf | nicht geprüft | Noch kein realer Ablauf zum Zählen. Keine Webhook-Wiederholung oder künstlicher Fehler in Produktion erzeugt. |

Ein Foto allein muss kein Ticket erzeugen und kann bereits an die Werkstatt
übergeben. Daher beim späteren Durchlauf zuerst die Textannahme abschließen,
die explizite Mitarbeiterübernahme prüfen und danach das Bild zum zugeordneten
Ticket senden. API-Annahme, Statusereignis und am Telefon bestätigter Empfang
sind getrennt zu protokollieren.

## Änderungen und tatsächlich ausgeführte Tests

Geändert wurden dieser Bericht, der aktuelle Projektstand und dessen
Prioritätshinweis in `AGENTS.md`. Anwendung und Pakete wurden nicht geändert.
Lokale Hilfsscripte, bereinigte Prüfergebnisse und das synthetische PNG bleiben
unter `artifacts/m1-2026-10-21/`, ausgeschlossen von Git und Docker. Geheimnisse,
Cookies, rohe Dashboard-Inhalte und vollständige personenbezogene Daten wurden
nicht in den Bericht übernommen.

Ausgeführt: lesende Git-/Railway-/Meta-Abfragen, die genannten angemeldeten
HTTP-Kontrollen und gültigen GET-Verifikationen sowie unter Python 3.14.3:

```powershell
$env:PYTHONPATH = 'tests'
.\.venv\Scripts\python.exe -m unittest test_whatsapp_reliability test_whatsapp_medien -q
```

**26 Tests bestanden** (9,545 Sekunden). Die Tests verwenden temporäre
SQLite-Datenbanken und simulierten Nachrichten-/Medientransport. Erwartete
Fehlerprotokolle stammen aus isolierten Testfällen. Dies ersetzt weder den
realen Meta-Ablauf noch einen erneuten Test unter Produktions-Python 3.12.
Der anfangs blockierte Netzwerkzugriff war nach freigegebener lesender Abfrage
verfügbar; der lokale Prüfhelfer wurde ohne Paketinstallation an die fehlende
Zeitzonendatenbank angepasst. Beides war kein nachgewiesener Produktfehler.

## Vorbereitete Fortsetzung

Reservierter, noch nicht verwendeter Marker: `M1-20261021-A1`.
Vor dem Senden Eigentum, Endziffern, Freischaltung und Ausgangszustand der
eigenen Unterhaltung prüfen; vorhandene fremde Gespräche bleiben unberührt.
Die Antworten jeweils passend zur tatsächlichen Rückfrage senden:

- Einstieg: „Ich möchte ein neues Anliegen melden: Ölwechsel für einen
  erfundenen VW Golf. Testmarker M1-20261021-A1.“
- Fahrzeugdaten bei Rückfrage: „VW Golf, Baujahr 2018, 85000 km.“
- Rückrufnummer nur bei Rückfrage: „030 00000000“ (erfundene Formulareingabe;
  Versandziel bleibt ausschließlich der bestätigte WhatsApp-Absender).
- Name bei Rückfrage: „Mara Beispiel“.
- Manuelle Werkstattinformation nach Übernahme: „M1-20261021-A1: Die Werkstatt
  hat übernommen. Dies ist eine manuelle Testantwort ohne Terminbestätigung.“
- Weitere Kundennachricht im manuellen Modus: „M1-20261021-A1: Bitte notieren,
  dass dies nur ein Test ist. Keine Reparatur beauftragt.“
- Bild: lokales `artifacts/m1-2026-10-21/pruefbild-m1-20261021.png`
  (480 × 320 Pixel, 4470 Bytes); Beschriftung
  „M1-20261021-A1 – synthetisches Prüfbild ohne Kundendaten“.

## Blockade und genau ein empfohlener nächster Schritt

Die erforderliche Telefonaktion fehlt: Teilnahme mit ausdrücklich bestätigtem
eigenem Testempfänger. Zusätzlich bleibt der direkte Laufzeit-Dateivergleich
technisch ungeprüft; der fehlende SSH-Schlüssel ist kein Produktfehler.

**Nächster Schritt:** Mikolaj bestätigt bei seiner Rückkehr den eigenen
Testempfänger anhand der Endziffern und führt mit uns den vorbereiteten
WhatsApp-Durchlauf am Telefon aus.

M1 bleibt bis zu den echten Nachweisen offen. Es bestätigt weder Coexistence
noch die Anbindung fremder Werkstätten.
