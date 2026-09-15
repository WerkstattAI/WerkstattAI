# WerkstattAI

Digitale Kundenannahme und Ticketverwaltung für Werkstätten mit Webchat,
Werkstatt-Dashboard und WhatsApp-Anbindung.

**Stand: funktionaler Prototyp. Vor dem Einsatz mit echten Kundendaten sind
Sicherheits- und Betriebsfragen zu beheben.**

- [Projektstand, bestätigte Schwachstellen und nächste Schritte](docs/projektstand.md)
- [Demo und Werkstattkonten](docs/demo-und-produktivkonto.md)
- [HTTP-Sicherheitsmaßnahmen](docs/http-sicherheit.md)
- [Datenschutzfunktionen und offene Angaben](docs/recht/betrieb-und-freigabe.md)
- [AVV-Grundlage – Entwurf](docs/recht/avv-grundlage.md)
- [Cloudflare-Worker für WhatsApp](cloudflare/whatsapp-webhook-proxy/README.md)

## Lokale Prüfungen

Die Python-Tests benötigen die Anwendungsabhängigkeiten und `httpx`.
Sie verwenden temporäre SQLite-Datenbanken und synthetische Daten.

```text
python -m unittest discover -s tests -q
node --test tests/test_privacy_worker.mjs
```

Die aktuell gepinnten Abhängigkeiten benötigen ein Sicherheitsupdate.
Die bekannten Grenzen der lokalen Tests und die noch ausstehende
PostgreSQL-/Docker-Prüfung sind im Projektstand dokumentiert.
