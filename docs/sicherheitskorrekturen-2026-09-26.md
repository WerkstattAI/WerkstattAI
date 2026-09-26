# Zugriffe und WhatsApp: Änderungen vom 26. September 2026

Dieser Stand ist lokal vorbereitet. Die Änderungen wurden noch nicht auf die
Live-Anwendung übertragen. Tests verwenden synthetische Daten, SQLite und
simulierte Meta-Antworten.

## Verhalten

- Der öffentliche Kundenchat bindet seine Gesprächskennung an ein signiertes
  HttpOnly-Browsercookie und an die Werkstatt. Webchat und WhatsApp haben getrennte
  serverseitige Sitzungen. Öffentliche Antworten enthalten nur die benötigten
  Statusangaben; der vollständige interne Gesprächsstand wird nicht ausgegeben.
- Ticketnummer und eingegebene Telefonnummer allein erlauben keinen Zugriff auf
  bestehende Vorgänge. Im Webchat zählt die Ticketzuordnung der eigenen Sitzung.
  Bei neuen WhatsApp-Tickets wird der bestätigte Absender separat gespeichert;
  die frei eingegebene Rückrufnummer erteilt keine Zugriffsberechtigung.
- Dashboard-Cookies werden gegen den aktuellen Benutzerbestand geprüft.
  Passwortreset, Benutzerlöschung sowie Änderungen an Rolle oder Werkstatt
  machen die bisherige Anmeldung ungültig.
- Das Freitextfenster verwendet den Zeitpunkt der Meta-Kundennachricht in UTC.
  Fehlende, ungültige oder zukünftige Zeitpunkte öffnen kein Fenster. Automatische
  Antworten und der gemeinsame Freitextsender prüfen dieses Fenster ebenfalls.
- Eingang, Änderungen am Ticket, Gesprächsstand und vorbereitete Antwort werden
  zusammen in einer Datenbanktransaktion gespeichert. Fehler rollen diese Einheit
  zurück. Wiederholte Webhooks verwenden eine vorhandene vorbereitete Antwort,
  ohne die Kundenannahme oder Notizen erneut auszuführen.
- Eindeutige vorübergehende Versandfehler (HTTP 429/5xx) können bei einem erneuten
  Webhook zugestellt werden. Bei Timeout oder Prozessabbruch nach der Versandreservierung
  bleibt der Status unklar; es erfolgt keine automatische erneute Sendung.
- Eine Mitarbeiterübernahme erhöht einen Änderungszähler. Vorbereitete Antworten
  werden bei geändertem Zähler unterdrückt. Eine bereits laufende Netzwerksendung
  lässt sich nicht zurückholen; sie setzt die manuelle Übernahme aber nicht zurück.

## Beim Einspielen beachten

1. Eine Datenbanksicherung erstellen und Wiederherstellung sowie Schemaänderung
   zuerst an einer Kopie unter der tatsächlichen Produktionsumgebung prüfen.
2. Die Anwendung mit dem neuen Schema und Code gemeinsam starten. `init_db()`
   ergänzt Felder für Absenderberechtigung, Meta-Zeitpunkt, Verarbeitungsstand,
   vorbereitete Antworten und den Übernahmezähler. Vorhandene Nachrichten werden
   als abgeschlossen behandelt und nicht nachträglich versandt.
3. Werkstattnutzer müssen sich erneut anmelden. Alte öffentliche Websitzungen
   werden nicht übernommen, weil ihre Browserzuordnung nicht nachweisbar war.
   Tickets und bisherige Gesprächsdaten bleiben für die Werkstatt erhalten.
4. Historische Tickets erhalten keine automatisch abgeleitete Kundenberechtigung
   aus ihrer Kontakttelefonnummer. Rückfragen zu solchen Vorgängen bearbeitet die
   Werkstatt. Neue WhatsApp-Tickets funktionieren mit der bestätigten Absendernummer.
5. Für alte WhatsApp-Nachrichten wird der ursprüngliche Meta-Zeitpunkt, soweit
   vorhanden und gültig, aus dem gespeicherten Ereignis übernommen. Andernfalls
   bleibt das Freitextfenster geschlossen, bis eine neue Kundennachricht eintrifft.
6. Das neue Browsercookie läuft nach 30 Tagen ab. Ablauf oder Löschung sowie
   „Neues Gespräch“ verhindern die Fortsetzung des bisherigen Webgesprächs;
   gespeicherte Daten werden dadurch nicht gelöscht.
7. Mit Testkonten zwei Werkstätten, neuen Kundenchat, eigenes/fremdes Ticket,
   Passwortreset, manuelle Übernahme sowie Export und Löschung prüfen. Bei
   unklarem Versand zuerst den tatsächlichen Zustellstand prüfen.

## Grenzen und nächste Arbeit

Die lokale Prüfung ersetzt keine PostgreSQL-/Docker-Prüfung, Lastprüfung oder
Erprobung mit einem Meta-Testkonto. Eine separate Hintergrundwarteschlange für
liegengebliebene Antworten ist nicht enthalten; Wiederaufnahme hängt vom erneuten
Webhook ab. Mediennachrichten werden gespeichert, aber noch nicht automatisch
inhaltlich bearbeitet. Abhängigkeitsupdates, Betriebsüberwachung, Backups sowie
die rechtlichen und vertraglichen Angaben bleiben offen; siehe
[Projektstand](projektstand.md).
