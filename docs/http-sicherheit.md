# HTTP-Schutz in WerkstattAI

## Anfragen begrenzen

Die Anwendung speichert Rate-Limit-Zähler atomar in PostgreSQL beziehungsweise
lokal in SQLite. Sie gelten gemeinsam über Prozesse und Neustarts hinweg.
In der Tabelle stehen nur mit `AUTH_SECRET` geschützte HMAC-Schlüssel, keine
IP-Adressen oder Anmelde-E-Mails. Abgelaufene Zähler werden bei weiteren
Anfragen regelmäßig entfernt.

| Bereich | Standardgrenze |
| --- | --- |
| Allgemeine Anfragen | 300 pro Minute und Client-IP |
| Chat-Nachrichten | zusätzlich 30 pro Minute und Client-IP |
| Login | zusätzlich 5 pro Minute und Client-IP |
| Login pro eingegebener E-Mail | 20 pro 15 Minuten, auch über mehrere IPs |
| WhatsApp-Webhooks einschließlich Alias | 600 pro Minute und Client-IP |

Es gelten feste Zeitfenster; unmittelbar an einer Fenstergrenze sind zwei
Kontingente kurz nacheinander möglich. IPv6-Adressen werden pro /64-Netz
zusammengefasst. Die vier Minutengrenzen sind über `RATE_LIMIT_*_PER_MINUTE`
konfigurierbar. Gemeinsam genutzte Internetanschlüsse teilen sich das
IP-Kontingent. `/health` bleibt für Railway erreichbar.

Bei Überschreitung antwortet die Anwendung mit **429** und `Retry-After`.
Der Chat zeigt die Wartezeit und erhält die noch nicht gesendete Nachricht.
Ein Ausfall des Zählerspeichers führt zu **503**, nicht zu unbegrenztem Zugriff.
Diese Grenzen ersetzen keinen vorgelagerten Schutz gegen große DDoS-Angriffe.

## Vertrauenswürdiger Proxy

Railway liefert die Client-IP über `X-Real-IP` und leitet Anfragen über sein
Edge-Netz weiter. Siehe [Railway: Netzwerkheader](https://docs.railway.com/networking/public-networking/specs-and-limits).
Die Anwendung berücksichtigt diesen Header ausschließlich von Adressen in
`TRUSTED_PROXY_CIDRS`. Für die vorhandene Railway-Anwendung ist das
`100.64.0.0/10`; die Konfiguration wird dort automatisch vorbelegt. Lokal ist
die Liste leer. Einträge, die das gesamte Internet freigeben, sind verboten.

Docker startet Uvicorn mit `--no-proxy-headers`, damit die Anwendung den
tatsächlichen Proxy erkennen kann. Fremde `X-Forwarded-For`- und
`CF-Connecting-IP`-Header werden für Rate-Limits nicht übernommen.
Bei Umzug auf einen anderen Proxy muss dessen Netz gezielt konfiguriert werden.

## Eingabegrenzen

- Chattext: 4096 Zeichen; Session- und Werkstatt-ID: 128; Telefonnummer: 32.
- Login-Passwort: 128 Zeichen; E-Mail: 254. Formularfelder sind zusätzlich
  je nach Zweck begrenzt, beispielsweise Notizen auf 4096 Zeichen.
- Anfragekörper: 32 KiB für Chat, 64 KiB sonst, 256 KiB für WhatsApp.
- WhatsApp: höchstens 100 Nachrichten und Statusereignisse pro Payload;
  Nachrichtentexte höchstens 4096 Zeichen.
- URLs: Pfad maximal 1024 Zeichen, Query maximal 2048 Bytes; HTTP-Header
  zusammen maximal 16 KiB. Ticketlisten liefern maximal 200 Einträge pro Abruf.
- Übertragung des Anfragekörpers: maximal 15 Sekunden.

Auch Anfragen ohne `Content-Length` oder mit falscher Größenangabe werden beim
Einlesen begrenzt, bevor ein Endpunkt Daten verarbeitet. Ungültige Felder
führen zu **422**, zu große Körper zu **413**. Validierungsantworten enthalten
keine Kopie eingegebener Passwörter oder Nachrichtentexte.

## Browserzugriffe und Sicherheitsheader

`CORS_ALLOWED_ORIGINS` ist standardmäßig leer. Der eigene Kundenchat und das
Dashboard funktionieren weiterhin auf ihrer jeweiligen Anwendungsdomain.
Für einen externen JavaScript-Client kann eine konkrete Origin freigegeben
werden, beispielsweise `https://kunden.example`. In Produktion ist HTTPS
erforderlich. Wildcards, URL-Pfade und Cross-Origin-Cookies sind nicht erlaubt.
Schreibzugriffe mit einer fremden, nicht zugelassenen Origin werden abgewiesen.

Alle Antworten einschließlich Fehlern erhalten CSP, `X-Content-Type-Options`,
`X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` und `Cache-Control`.
Eigene Seitenskripte erhalten eine zufällige Nonce pro Antwort; unfreigegebene
Inline-Skripte und Inline-Eventhandler werden blockiert. Die bestehenden
Inline-CSS-Stile bleiben erlaubt. Grundlage:
[MDN: Content Security Policy](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP).

Seiten dürfen nicht in fremden Frames eingebettet werden. Externe Werkstätten
können den Kundenchat verlinken oder einen freigegebenen JavaScript-Client
verwenden. `form-action` erlaubt zusätzlich `https://wa.me`, damit die
vorhandene manuelle WhatsApp-Weiterleitung nach einer Formularaktion funktioniert.
Produktionsantworten setzen HSTS; Sitzungscookies sind dort immer `Secure`.
API-Dokumentation unter `/docs`, `/redoc` und `/openapi.json` ist in Produktion
deaktiviert. Entwicklungs-Dokumentationsseiten erhalten eine eigene CSP für
die von FastAPI verwendeten CDN-Dateien.

## Produktionsprüfung

`APP_ENV=production` und `staging` aktivieren die Produktionsprüfungen.
Die Railway-Umgebung `production` aktiviert sie auch bei einer abweichenden
`APP_ENV`-Angabe. Unbekannte Umgebungsnamen werden abgewiesen.

Der Start wird vor der Datenbankinitialisierung abgebrochen, wenn `AUTH_SECRET`
zu kurz ist, aus zu wenigen unterschiedlichen Zeichen besteht oder einen
bekannten Platzhalter enthält. Mindestens 32 Zeichen und ein eigenes zufällig
erzeugtes Secret verwenden. Ein Secret-Wechsel macht bestehende
Anmeldesitzungen und die zugehörigen Rate-Limit-Schlüssel ungültig.

Unsichere Cookie-, CORS-, Proxy- und Rate-Limit-Konfigurationen werden ebenfalls
abgewiesen. Bei einem WhatsApp-Zugriffstoken ist ein App-Secret erforderlich;
ohne App-Secret akzeptiert der Produktionswebhook keine Nachrichten.

Beim erstmaligen Anlegen eines Produktions-Admin-Kontos ist ein eigenes
Bootstrap-Passwort mit mindestens 12 Zeichen erforderlich. **Bereits
vorhandene Passwörter werden nicht geändert oder gegen das Bootstrap-Passwort
ausgetauscht.** Das zuvor bekannte Admin-Standardpasswort muss deshalb separat
über die Kontoverwaltung geändert werden.
