# WerkstattAI

Digitale Kundenannahme und Ticketverwaltung für Werkstätten mit Webchat,
Werkstatt-Dashboard und WhatsApp-Anbindung.

**Stand: funktionaler Prototyp. Vor dem Einsatz mit echten Kundendaten sind
Sicherheits- und Betriebsfragen zu beheben.**

- [Projektstand, bestätigte Schwachstellen und nächste Schritte](docs/projektstand.md)
- [Zugriffs- und WhatsApp-Korrekturen: Einspielhinweise](docs/sicherheitskorrekturen-2026-09-26.md)
- [Kundenkommunikation: Nachrichten, Zustände und Migration](docs/kundenkommunikation.md)
- [Demo und Werkstattkonten](docs/demo-und-produktivkonto.md)
- [HTTP-Sicherheitsmaßnahmen](docs/http-sicherheit.md)
- [Datenschutzfunktionen und offene Angaben](docs/recht/betrieb-und-freigabe.md)
- [AVV-Grundlage – Entwurf](docs/recht/avv-grundlage.md)
- [Cloudflare-Worker für WhatsApp](cloudflare/whatsapp-webhook-proxy/README.md)
- [Geschützte WhatsApp-Bildvorschau und Betriebsgrenzen](docs/whatsapp-bilder.txt)

## Lokale Prüfungen

Die Python-Tests benötigen die Abhängigkeiten aus `requirements-test.txt`.
Sie verwenden temporäre SQLite-Datenbanken und synthetische Daten.

```text
python -m unittest discover -s tests -q
node --test tests/test_privacy_worker.mjs
```

Die aktuell gepinnten Abhängigkeiten benötigen ein Sicherheitsupdate.
Die PostgreSQL-/Docker-Prüfung vom 19. Oktober 2026, der veröffentlichte Stand
und die verbleibenden Sicherheits- und Betriebsaufgaben sind im
[Projektstand](docs/projektstand.md) dokumentiert.
