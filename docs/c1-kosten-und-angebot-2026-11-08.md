# C1 – Kostenmodell und Angebotsentwurf

Stand: 8. November 2026. Die Preise wurden vom Nutzer freigegeben: 149 €/Monat, 299 € Einrichtung, erste drei Pilotbetriebe für drei bezahlte Monate zu 99 €/Monat; Meta separat. Die weiteren Detailbedingungen dieses Entwurfs bleiben abzustimmen. Keine Preisänderung auf der Website, kein aktiviertes Abrechnungssystem. Die ältere Empfehlung vom 12. September (99 €/Monat, 199 € Einrichtung) bleibt als Historie erhalten.

## Empfehlung zur Entscheidung

- Ein Paket für einen Standort und eine WhatsApp-Nummer: **149 € monatlich**.
- Einrichtung: **299 € einmalig**, nach erfolgreicher technischer Abnahme.
- Erste drei Pilotbetriebe: **99 €/Monat für die ersten drei bezahlten Monate**, danach 149 €. Einrichtung weiterhin 299 €.
- Meta-Nachrichten separat zum tatsächlichen Tarif, möglichst direkt über das Konto der Werkstatt. Keine unbegrenzten Nachrichten im Abonnement versprechen.
- Alle Beträge sind Kalkulationswerte ohne Umsatzsteuer. Steuerstatus und endgültige Preiskennzeichnung vor Veröffentlichung klären; dies ist kein veröffentlichungsfertiger Bruttopreis.

## Nachgewiesener Stand und Annahmen

Die Anwendung ruft derzeit kein kostenpflichtiges Sprachmodell auf. `OPENAI_API_KEY` ist lediglich als optionale spätere Konfiguration vorhanden. Externe KI-Tokenkosten dieser Implementierung: 0 €. Entwicklungsabonnements gehören zu allgemeinen Betriebskosten, nicht zu diesem Laufzeitwert.

Railway-Messwerte vom 8. November zeigen rund 75,74 MB Anwendungsspeicher, 54,06 MB PostgreSQL-Speicher und 220,18 MB Datenbankvolume. Dies sind Momentwerte im Testbetrieb, keine Monatsrechnung und kein Lastnachweis für zehn Kunden.

[Railway-Preise](https://docs.railway.com/pricing): Hobby mindestens 5 USD, Pro mindestens 20 USD monatlich; enthaltenes Guthaben nicht zusätzlich zum Verbrauch addieren. RAM 10 USD/GB-Monat, CPU 20 USD/vCPU-Monat, ausgehender Transfer 0,05 USD/GB, Volume 0,15 USD/GB-Monat. Tarif, Rechnung, Steuern und Wechselkurs sind vor dem Pilotbetrieb zu bestätigen.

Planungsbudget für gemeinsame Infrastruktur: **25 € Grundbudget plus 5 € je Werkstatt monatlich**. Das ist eine vorsichtige Budgetannahme für Hosting, Datenbank, Transfer, kleine Sicherungs-/Domainreserve, keine aus Momentwerten errechnete Anbieterrechnung. Zusätzliche Backuplösung, Domain oder E-Mail sind noch nicht mit tatsächlichen Rechnungen belegt. Kein exakter USD/EUR-Wechselkurs wird unterstellt.

Fotos werden geschützt bei Meta abgerufen, nicht dauerhaft als eigenes Fotoarchiv gespeichert. Annahme pro Betrieb: 100 Anfragen mit je zwei Bildern, durchschnittlich 2 MB und je drei Abrufen = etwa 1,2 GB Transfer/Monat; maximal unterstützte Bildgröße 5 MB. Transfer ist im Budget enthalten. Dauerhafte Verfügbarkeit alter Bilder nicht versprechen.

## Meta: aktueller Tarif statt alter Gratisannahme

[Offizielle Preisdokumentation](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing), im angemeldeten Browser geprüft, Stand 30. September 2026; EUR-Tabelle „EUR-Listenpreise“, gültig ab 1. Oktober 2026, Deutschland-Zeile:

| Kategorie | EUR je zugestellter Nachricht |
| --- | ---: |
| Service nach Freikontingent | 0,0456 |
| Utility | 0,0456 |
| Authentication | 0,0456 |
| Marketing | 0,1131 |

Eingehende Kundennachrichten kosten nichts. Die ersten 1.000 zugestellten Service-Nachrichten je Geschäftsnummer und Monat sind kostenlos; darüber fallen Gebühren an. Utility-Vorlagen sind auch innerhalb des 24-Stunden-Fensters kostenpflichtig. Das Fenster erlaubt freie Antworten, bedeutet aber keine unbegrenzte kostenlose Nutzung. Ohne Zahlungsmethode kann nach Verbrauch des Freikontingents die Zustellung ausbleiben. Tarif hängt von Empfängerland und Abrechnungswährung ab. Die separate Meta-Business-Agent-Tokengebühr betrifft nicht den hier verwendeten Regelassistenten.

Die verlinkte EUR-Datei wurde trotz CSV-Endung als XLSX geliefert; Kopfzeile, Kategorien und Deutschland-Zeile wurden aus dem Tabelleninhalt gelesen. Maßgeblich ist der aktuelle Kontotarif; keine flüchtige CDN-Adresse als dauerhaften Quellenlink verwenden.

Szenarien für deutsche Empfänger, eine Nummer je Werkstatt, acht zugestellte Service-Antworten je Anfrage, keine Marketingnachrichten, keine Mengenrabatte oder Werbe-Einstiegsfenster:

| Anfragen/Monat | Service gesamt | Utility zusätzlich | Meta/Monat |
| --- | ---: | ---: | ---: |
| 100 | 800 | 50 | 2,28 € |
| 300 | 2.400 | 100 | 68,40 € |
| 600 | 4.800 | 200 | 182,40 € |

Formel: `max(0, Service - 1000) × 0,0456 + Utility × 0,0456`. Menschliche und automatische Antworten zählen mit. Annahmen sind keine gemessenen Gesprächslängen. Ein Bot darf keine unnötigen Einzelnachrichten erzeugen. Bei 300 Anfragen kostet das empfohlene Standardangebot zusammen mit Meta beispielhaft 217,40 €/Monat; im Pilot 167,40 €.

## Betrieb mit 1, 5 und 10 Werkstätten

Unterstellt: gemeinsamer Betrieb, 300 Anfragen pro Werkstatt, Meta separat durch Kunden bezahlt. Supportbewertung: eine Stunde pro Werkstatt und Monat zu intern 30 €/h, einschließlich laufender Betreuung. Keine Aussage über marktüblichen Stundenlohn.

| Werkstätten | Infrastruktur gesamt | Bewerteter Support | Umsatz bei 149 € | Verbleibender Beitrag | Bei Pilotpreis 99 € |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 30 € | 30 € | 149 € | 89 € | 39 € |
| 5 | 50 € | 150 € | 745 € | 545 € | 295 € |
| 10 | 75 € | 300 € | 1.490 € | 1.115 € | 615 € |

Die Pilotspalte ist ein Vergleich bei einheitlich 99 €, keine Erweiterung der Empfehlung auf zehn Pilotkunden. Beitrag = Umsatz minus Infrastruktur minus bewerteter Support, **kein Nettogewinn**. Entwicklung, Vertrieb, Buchhaltung, Versicherung, Steuern, Zahlungsausfälle und weitere allgemeine Kosten sind nicht abgezogen. Bei zwei statt einer Supportstunde sinkt der Beitrag um 30 € je Betrieb. Bei eigener Übernahme der mittleren Meta-Nutzung sinkt er zusätzlich um 68,40 € je Betrieb; deshalb keine pauschale Inklusivzusage.

Infrastruktur pro Betrieb: 30 €/10 €/7,50 € bei 1/5/10. Geschätzter zusätzlicher Betrieb: 5 € Infrastruktur plus 30 € Betreuung, solange gemeinsamer Betrieb innerhalb des Budgets bleibt. Größere Ressourcenstufen können Sprünge verursachen.

Einrichtung: vier Stunden zu 30 € = 120 € interner Aufwand, plus beispielhaft 20 € direkte Ausgaben; bei 299 € bleiben 159 € vor Gemeinkosten. Erster Pilot mit acht Stunden: 240 € plus 20 €, verbleibend 39 €. Zeit tatsächlich erfassen. Bei bisheriger Einrichtung zu 199 € wäre dieses Achtstunden-Szenario bereits negativ.

## Angebotsentwurf für das Kundengespräch

**WerkstattAI – Anfragen aus WhatsApp und Web an einem Ort**

Für einen Werkstattstandort und eine WhatsApp-Nummer: strukturierte Kundenanfragen, Tickets, Werkstatt-Dashboard, manuelle Antworten und unterstützte Bildvorschau. Die Werkstatt entscheidet über Termine und Reparaturaufträge. Keine Telefonannahme, automatische verbindliche Terminbuchung oder dauerhafte Fotoarchivierung zugesagt.

**Preisvorschlag:** 149 €/Monat plus 299 € Einrichtung; für die ersten drei Pilotpartner 99 €/Monat während der ersten drei bezahlten Monate. Meta-Nachrichten zusätzlich nach tatsächlichem Verbrauch. Steuerkennzeichnung vor Verwendung ergänzen.

Einrichtung umfasst Zugang, Einrichtung der verfügbaren Verbindung, Prüfung von Text und Testbild, einen abgestimmten Standardablauf und eine Einweisung bis 60 Minuten. Sonderintegrationen, Nummernmigration und individuelle Prozessentwicklung werden gesondert vereinbart; Anschluss erst nach geklärten technischen Voraussetzungen.

Vorgeschlagene Nutzungsgrenze: 500 neue Anfragen/Tickets pro Monat. Kein technisches Limit bereits umgesetzt. Vor Überschreitung gemeinsam Bedarf und Preis abstimmen; keine überraschende Nachberechnung. Für einen nutzbaren Vertragsumfang müssen Zähler und Warnung vor Einführung ergänzt werden.

Vorgeschlagene Probe: 14 Tage ab funktionsfähiger Abnahme ohne WerkstattAI-Abonnementgebühr. Meta-Kosten können währenddessen entstehen. Einrichtung erst bei ausdrücklicher Fortsetzung nach der Probe berechnen; kein automatischer Übergang in ein kostenpflichtiges Abo. Dieses Modell trägt WerkstattAI zunächst selbst: auf drei Pilotkunden begrenzen. Erster bezahlter Pilotmonat inklusive Einrichtung: 398 € plus Meta.

Monatliche Abrechnung im Voraus per Rechnung/Überweisung, zunächst kein Zahlungsanbieter erforderlich. Kündigung zum Ende des bezahlten Monats ohne weitere Mindestlaufzeit. Support per E-Mail, Rückmeldung als Ziel innerhalb von zwei Werktagen; bis 30 Minuten Einweisung/Anwendungsberatung monatlich enthalten. Fehlerbehebung im Produkt zählt nicht zu diesem Beratungskontingent. Zusatzarbeiten nur nach Angebot. Keine 24/7-Bereitschaft und keine garantierte Reaktionsfrist vereinbaren, bevor der Betrieb dafür eingerichtet ist.

Bei Vertragsende: Exportweg, Zugangsende und Löschfristen vor Vertragsverwendung verbindlich festlegen und testen. Keine sofortige automatische Löschung zusagen. Dieser Entwurf ist keine geprüfte Vertragsvorlage.

## Offene Umsetzung und nächste Entscheidung

`app/subscriptions.py` berücksichtigt das gespeicherte `subscription_ends_at` bisher nicht für aktive Abonnements; `past_due` bleibt ebenfalls aktiv. Die Suche ergab keine Stripe-/PayPal-Integration. Vor bezahltem Start Rechnungsvorgang, Ablauf, Zahlungsverzug, Kündigung, Zugriff und Datenübergabe umsetzen bzw. testen. C1 ist damit noch nicht abgeschlossen.

Jetzt entscheiden: 149 €/299 € Standard, zeitlich begrenzter Pilot 99 €, Meta separat; danach Website und Präsentation an die freigegebenen Bedingungen anpassen. Preise nach den ersten drei Betrieben anhand echter Supportstunden, Nachrichtenanzahl, Rechnung und Kundennutzen prüfen.
