"""M2-Gesamtkette über echte Routen; nur Meta-HTTP und die Prüfuhr sind simuliert."""
import io
import json
import os
import subprocess
import sys
import time
import unittest
import uuid
from dataclasses import replace
from email.message import Message
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from fastapi.testclient import TestClient
import app.db as db
import app.main as main
import app.web as web
import app.whatsapp as wa
import app.whatsapp_anschluss as anschluss
import app.whatsapp_synchronisierung as sync
import app.whatsapp_verbindungen as verbindungen
from app.auth import SESSION_COOKIE, create_session_token
from app.tickets import find_ticket_by_id
from anschlussdaten import MetaSimulation
import test_whatsapp_verbindungen as grundlage


class AbnahmeFaelle:
    def setUp(self):
        grundlage.VerbindungsTests.setUp(self)
        self.config = replace(self.konfiguration,
            database_url=os.environ["WERKSTATTAI_TEST_POSTGRES_URL"] if self.postgres else None,
            whatsapp_app_id="111", whatsapp_signup_config_id="222",
            whatsapp_signup_origin="https://testserver", whatsapp_app_secret="synthetische-abnahmesignatur",
            whatsapp_signup_graph_version="v26.0", whatsapp_graph_api_version="v26.0")
        for modul in (db, main, web, anschluss, verbindungen):
            self.stack.enter_context(patch.object(modul, "settings", self.config))
        db.init_db()
        self.zeit = int(time.time())
        self.werkstaetten, self.sendungen, self.medienabrufe, self.seiten = [], [], [], {}
        self.fruehe_rueckmeldung = None
        for index in range(2):
            wid = "abnahme-" + uuid.uuid4().hex
            w = {"wid": wid, "konto": str(uuid.uuid4().int)[:16], "nummer": str(uuid.uuid4().int)[:16],
                 "betrieb": "49000000100" + str(index), "kunde": "4900000020000", "email": wid + "@example.invalid"}
            with db.atomic_database() as conn:
                conn.execute("INSERT INTO workshops (id, name, subscription_status) VALUES (?, ?, 'active')",
                             (wid, "Abnahmewerkstatt " + str(index + 1)))
                conn.execute("INSERT INTO users (email, role, workshop_id, password_hash) VALUES (?, 'owner', ?, 'synthetisch')",
                             (w["email"], wid))
            w["cookie"] = create_session_token({"email": w["email"], "role": "owner", "workshop_id": wid})
            w["client"] = self.stack.enter_context(TestClient(main.app, base_url="https://testserver"))
            w["client"].cookies.set(SESSION_COOKIE, w["cookie"])
            w["client"].headers["origin"] = "https://testserver"
            m = w["meta"] = MetaSimulation()
            m.token = "synthetischer-zugang-" + wid
            m.debug["granular_scopes"] = [{"scope": r, "target_ids": [w["konto"]]} for r in m.debug["scopes"]]
            m.antworten.update({("GET", w["konto"] + "/phone_numbers"): {"data": [{"id": w["nummer"]}]},
                ("GET", w["nummer"]): {"id": w["nummer"], "display_phone_number": w["betrieb"],
                    "is_on_biz_app": True, "platform_type": "CLOUD_API"},
                ("GET", w["konto"] + "/subscribed_apps"): {"data": []},
                ("POST", w["konto"] + "/subscribed_apps"): {"success": True},
                ("POST", w["nummer"] + "/smb_app_data"): {"messaging_product": "whatsapp", "request_id": "synthetisch-" + wid}})
            self.werkstaetten.append(w)
        self.stack.enter_context(patch("urllib.request.OpenerDirector.open", side_effect=self.http))

    def antwort(self, daten, typ="application/json"):
        a = io.BytesIO(daten if isinstance(daten, bytes) else json.dumps(daten).encode())
        a.status, a.headers = 200, Message()
        a.headers["Content-Type"] = typ
        return a

    def http(self, anfrage, *args, **kwargs):
        self.assertIsNone(db._TRANSACTION_CONNECTION.get(), "Kein HTTP innerhalb einer Transaktion")
        u = urlsplit(anfrage.full_url)
        self.assertEqual(u.scheme, "https")
        self.assertIn(u.netloc, {"graph.facebook.com", "lookaside.fbsbx.com"})
        pfad = u.path.removeprefix("/v26.0/")
        q = parse_qs(u.query)
        token = anfrage.get_header("Authorization", "").removeprefix("Bearer ")
        w = next((w for w in self.werkstaetten if token == w["meta"].token
                  or q.get("input_token") == [w["meta"].token]
                  or q.get("code", [""])[0].startswith("synthetischer-einmalcode-" + w["wid"])), None)
        self.assertIsNotNone(w, "Unbekannter externer Zugriff im isolierten Transport")
        if u.netloc == "lookaside.fbsbx.com":
            self.assertEqual(u.path, "/synthetisches-bild")
            self.medienabrufe.append(w["wid"])
            return self.antwort(b"\x89PNG\r\n\x1a\nPruefbild", "image/png")
        if pfad == "777":
            self.assertEqual(q["phone_number_id"], [w["nummer"]])
            return self.antwort({"mime_type": "image/png", "url": "https://lookaside.fbsbx.com/synthetisches-bild"})
        if pfad == w["nummer"] + "/messages":
            self.assertEqual(anfrage.get_method(), "POST")
            daten = json.loads(anfrage.data)
            self.assertEqual(daten["to"], w["kunde"])
            mid = "wamid.abnahme-versand-" + str(len(self.sendungen) + 1)
            self.sendungen.append((w["wid"], mid, daten))
            if self.fruehe_rueckmeldung:
                self.fruehe_rueckmeldung(w, mid)
            return self.antwort({"messages": [{"id": mid}]})
        if pfad == w["konto"] + "/subscribed_apps" and anfrage.get_method() == "POST":
            w["meta"].antworten[("GET", pfad)] = {"data": [{"whatsapp_business_api_data": {"id": "111"}}]}
        return w["meta"].open(anfrage, *args, **kwargs)

    def post(self, w, bereich, aktion, **daten):
        return w["client"].post(f"/dashboard/whatsapp/{bereich}/{aktion}",
            json={"workshop_id": w["wid"], **daten}, follow_redirects=False)

    def verbinden(self, w):
        self.assertFalse(verbindungen.verbindungsstatus(w["wid"])["versand_bereit"])
        # Nur die Uhr läuft beim echten Signup 60 Sekunden früher. Keine
        # Anschlusszeile oder Autorisierung wird durch die Fixture geschrieben.
        with patch.object(anschluss.time, "time", return_value=self.zeit - 60):
            a = self.post(w, "verbinden", "start")
            self.assertEqual(a.status_code, 200, a.text)
            w["kennung"] = a.json()["kennung"]
            daten = {"kennung": w["kennung"], "code": "synthetischer-einmalcode-" + w["wid"] + w["kennung"],
                     "waba_id": w["konto"], "phone_number_id": w["nummer"],
                     "meta_ursprung": "https://www.facebook.com", "ereignis": "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING"}
            a = self.post(w, "verbinden", "abschluss", **daten)
            self.assertEqual(a.status_code, 200, a.text)
            self.assertEqual(a.json()["zustand"], "abgeschlossen")
        self.assertEqual(self.post(w, "verbinden", "abschluss", **daten).status_code, 409)
        v = verbindungen.verbindungsstatus(w["wid"])
        self.assertEqual((v["version"], v["autorisierung"], v["coexistence_bereit"]), (2, "bestaetigt", 0))
        self.assertEqual(verbindungen.zugang_fuer_werkstatt(w["wid"]).token, w["meta"].token)
        for aufruf in (("GET", "oauth/access_token"), ("GET", "debug_token"),
                       ("GET", w["konto"] + "/phone_numbers"), ("POST", w["konto"] + "/subscribed_apps")):
            self.assertEqual(w["meta"].aufrufe.count(aufruf), 1)
        self.assertFalse(any("register" in p for _, p in w["meta"].aufrufe))

    def paket(self, w, feld, **wert):
        return {"object": "whatsapp_business_account", "entry": [{"id": w["konto"], "time": self.zeit,
            "changes": [{"field": feld, "value": {"messaging_product": "whatsapp",
                "metadata": {"phone_number_id": w["nummer"]}, **wert}}]}]}

    def webhook(self, p, erwartet=200, signatur=True):
        roh = json.dumps(p).encode()
        kopf = {"content-type": "application/json"}
        if signatur:
            kopf["x-hub-signature-256"] = signatur if isinstance(signatur, str) else wa.build_signature(roh, self.config.whatsapp_app_secret)
        a = TestClient(main.app, base_url="https://testserver").post("/webhooks/whatsapp", content=roh, headers=kopf)
        self.assertEqual(a.status_code, erwartet, a.text)
        return a

    def nachricht(self, w, mid, text="Synthetische Kundeninformation", typ="text", zeit=None):
        n = {"id": mid, "from": w["kunde"], "timestamp": str(self.zeit - 5 if zeit is None else zeit), "type": typ}
        if typ == "text":
            n["text"] = {"body": text}
        if typ == "image":
            n["image"] = {"id": "777", "mime_type": "image/png"}
        return n

    def historie(self, w, *, teil=1, fortschritt=100, nachrichten=None):
        return self.paket(w, "history", history=[{"metadata": {"phase": 0, "chunk_order": teil, "progress": fortschritt},
            "threads": [{"id": w["kunde"], "messages": nachrichten or []}]}])

    def nachrichten(self, w):
        return wa.list_whatsapp_messages(workshop_id=w["wid"], customer_phone=w["kunde"])

    def kontrolle(self, w):
        return db.get_whatsapp_conversation_control(workshop_id=w["wid"], customer_phone=w["kunde"])

    def seite(self, name, w, pfad="/dashboard/whatsapp/verbinden"):
        a = w["client"].get(pfad, params={"phone": w["kunde"]})
        self.assertEqual(a.status_code, 200, a.text[:200])
        self.seiten[name] = {"html": a.text, "csp": a.headers["content-security-policy"]}

    def synchronisieren(self, w):
        self.seite("offen", w)
        a = self.post(w, "synchronisierung", "fortsetzen")
        self.assertEqual(a.status_code, 200, a.text)
        self.assertFalse(a.json()["technisch_bereit"])
        self.post(w, "synchronisierung", "fortsetzen")
        self.assertEqual(w["meta"].aufrufe.count(("POST", w["nummer"] + "/smb_app_data")), 2)
        alt = self.nachricht(w, "wamid.historie-" + w["wid"], typ="media_placeholder", zeit=self.zeit - 3600)
        lieferung = self.historie(w, nachrichten=[alt])
        with patch.object(sync, "verarbeite_offene"):
            self.webhook(lieferung)
        self.assertFalse(sync.status(w["wid"])["technisch_bereit"])
        # Ein frischer Prozess setzt ausschließlich das vorhandene Journal fort.
        skript = """import sys
from unittest.mock import patch
from app import whatsapp_synchronisierung as s
with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('Echtes HTTP gesperrt')):
    assert not s.status(sys.argv[1])['technisch_bereit']
    s.verarbeite_offene(sys.argv[1])
    assert s.status(sys.argv[1])['technisch_bereit']
"""
        lauf = subprocess.run([sys.executable, "-c", skript, w["wid"]], capture_output=True, text=True, timeout=40,
            env={**os.environ, "DATABASE_URL": self.config.database_url or "", "APP_ENV": "test"})
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        self.webhook(lieferung)
        self.webhook(self.paket(w, "history", messages=[self.nachricht(w, alt["id"], typ="image", zeit=self.zeit - 3600)]))
        self.webhook(self.paket(w, "smb_app_state_sync", state_sync=[{"type": "contact", "action": "add",
            "contact": {"phone_number": w["kunde"], "full_name": "Synthetischer Kontakt"}, "metadata": {"timestamp": self.zeit - 10}}]))
        self.assertTrue(sync.status(w["wid"])["technisch_bereit"])
        self.assertFalse(sync.status(w["wid"])["kontakte_vollstaendig"])
        n = self.nachrichten(w)
        self.assertEqual(len(n), 1)
        self.assertTrue(n[0]["historisch"])
        self.assertIsNone(n[0]["ticket_id"])
        self.assertEqual(n[0]["message_type"], "image")
        w["bild"] = n[0]["id"]
        self.assertFalse(wa.whatsapp_customer_service_window_for_phone(workshop_id=w["wid"], customer_phone=w["kunde"])["service_window_open"])
        with db.get_conn() as conn:
            for tabelle in ("tickets", "conversation_sessions"):
                self.assertEqual(conn.execute(f"SELECT COUNT(*) AS n FROM {tabelle} WHERE workshop_id = ?", (w["wid"],)).fetchone()["n"], 0)
        self.seite("abgeschlossen", w)

    def freigabe_nur_im_fixture(self):
        # Phase 2: ausschließlich diese isolierten Datenbanken simulieren die
        # spätere Betriebsfreigabe. Es gibt keine entsprechende Produktroute.
        with db.atomic_database() as conn:
            for w in self.werkstaetten:
                self.assertEqual(conn.execute("SELECT coexistence_bereit FROM whatsapp_verbindungen WHERE workshop_id = ?", (w["wid"],)).fetchone()["coexistence_bereit"], 0)
                conn.execute("UPDATE whatsapp_verbindungen SET coexistence_bereit = 1 WHERE workshop_id = ?", (w["wid"],))

    def echo(self, w, mid, zeit=None):
        return self.paket(w, "smb_message_echoes", message_echoes=[{"id": mid, "from": w["betrieb"], "to": w["kunde"],
            "timestamp": str(self.zeit - 1 if zeit is None else zeit), "type": "text", "text": {"body": "Antwort aus der Business-App"}}])

    def rueckmeldung(self, w, mid):
        return self.paket(w, "messages", statuses=[{"id": mid, "recipient_id": w["kunde"], "timestamp": str(self.zeit), "status": "read"}])

    def test_zwei_werkstaetten_vom_signup_bis_zum_offboarding(self):
        for w in self.werkstaetten:
            self.verbinden(w)
            self.synchronisieren(w)
            self.assertTrue(anschluss.automatik_gesperrt(w["wid"]))
            w["gehalten"] = self.paket(w, "messages", messages=[self.nachricht(w, "wamid.gehalten-" + w["wid"])])
            self.assertEqual(self.webhook(w["gehalten"]).json()["manual_pending"], 1)
            self.assertEqual(len(self.nachrichten(w)), 1)
        self.assertEqual(self.sendungen, [])
        self.freigabe_nur_im_fixture()
        for w in self.werkstaetten:
            self.assertEqual(self.webhook(w["gehalten"]).json()["manual_pending"], 1)
            for i, text in enumerate(("Audi A4 2019 120000 km", "Inspektion und Ölwechsel", w["kunde"], "Synthetische Kundin")):
                p = self.paket(w, "messages", messages=[self.nachricht(w, f"wamid.intake-{w['wid']}-{i}", text)])
                vorher = len(self.sendungen)
                self.assertEqual(self.webhook(p).json()["processed"], 1)
                self.webhook(p)
                self.assertEqual(len(self.sendungen), vorher + 1)
            with db.get_conn() as conn:
                tickets = conn.execute("SELECT ticket_id FROM tickets WHERE workshop_id = ?", (w["wid"],)).fetchall()
            self.assertEqual(len(tickets), 1)
            w["ticket"] = tickets[0]["ticket_id"]
            ticket = find_ticket_by_id(w["ticket"], w["wid"])
            self.assertEqual(ticket["verified_customer_phone"], w["kunde"])
            self.assertEqual(self.kontrolle(w)["active_ticket_id"], w["ticket"])
            mid = self.sendungen[-1][1]
            kontrolle = self.kontrolle(w)
            self.webhook(self.rueckmeldung(w, mid))
            self.webhook(self.echo(w, mid))
            self.assertEqual(self.kontrolle(w), kontrolle)
            self.assertEqual(next(n for n in self.nachrichten(w) if n["wa_message_id"] == mid)["status"], "read")
            daten = {"workshop_id": w["wid"], "customer_phone": w["kunde"], "ticket_id": w["ticket"],
                "reply_text": "Manuelle Information der Werkstatt", "purpose": "workshop_notification", "message_id": "manuell-" + w["wid"]}
            vorher = len(self.sendungen)
            for _ in range(2):
                a = w["client"].post("/dashboard/whatsapp/reply", data=daten, follow_redirects=False)
                self.assertEqual(a.status_code, 303)
                self.assertIn("reply_status=sent", a.headers["location"])
            self.assertEqual(len(self.sendungen), vorher + 1)
            self.assertEqual(self.kontrolle(w)["mode"], "manual")
            # Die echte Fortsetzen-Route erhält eine kontrollierte ältere Uhr,
            # damit das folgende Telefon-Echo eindeutig später liegt.
            with patch("time.time", return_value=self.zeit - 10):
                a = w["client"].post("/dashboard/whatsapp/control", data={"customer_phone": w["kunde"], "mode": "assistant"}, follow_redirects=False)
            self.assertEqual(a.status_code, 303)
            self.assertEqual(self.kontrolle(w)["mode"], "assistant")
            # Eine offene Kundenfrage wird über den echten Eingang angelegt.
            self.webhook(self.paket(w, "messages", messages=[self.nachricht(w, "wamid.frage-" + w["wid"], "Was kostet die Reparatur?")]))
            ticket = find_ticket_by_id(w["ticket"], w["wid"])
            self.assertTrue(ticket["customer_question_open"])
            vorher = len(self.sendungen)
            p = self.echo(w, "wamid.telefon-" + w["wid"])
            self.webhook(p)
            kontrolle = self.kontrolle(w)
            self.assertEqual(kontrolle["mode"], "manual")
            self.webhook(p)
            self.assertEqual(self.kontrolle(w), kontrolle)
            nachher = find_ticket_by_id(w["ticket"], w["wid"])
            self.assertEqual(nachher["status"], ticket["status"])
            self.assertTrue(nachher["customer_question_open"])
            self.assertEqual(sum(n["wa_message_id"] == "wamid.telefon-" + w["wid"] for n in self.nachrichten(w)), 1)
            self.webhook(self.paket(w, "messages", messages=[self.nachricht(w, "wamid.manuell-eingang-" + w["wid"], "Weitere Information")]))
            self.assertEqual(len(self.sendungen), vorher)
            self.seite("telefon", w, "/dashboard/whatsapp")
            a = w["client"].post("/dashboard/whatsapp/control", data={"customer_phone": w["kunde"], "mode": "assistant"}, follow_redirects=False)
            self.assertEqual(a.status_code, 303)
            kontrolle = self.kontrolle(w)
            self.webhook(p)
            self.webhook(self.echo(w, "wamid.spaet-" + w["wid"], self.zeit - 20))
            self.assertEqual(self.kontrolle(w), kontrolle)
        a, b = self.werkstaetten
        self.assertEqual(a["client"].get(f"/dashboard/whatsapp/medien/{a['bild']}").status_code, 200)
        vorher = self.kontrolle(b)
        self.webhook(self.paket(a, "account_update", event="ACCOUNT_OFFBOARDED"))
        self.assertEqual(verbindungen.verbindungsstatus(a["wid"])["autorisierung"], "widerrufen")
        self.assertTrue(anschluss.automatik_gesperrt(a["wid"]))
        with self.assertRaises(verbindungen.VerbindungsFehler):
            verbindungen.zugang_fuer_werkstatt(a["wid"])
        self.assertEqual(a["client"].get(f"/dashboard/whatsapp/medien/{a['bild']}").status_code, 409)
        anzahl = len(self.sendungen)
        self.assertFalse(wa.send_whatsapp_text_message(workshop_id=a["wid"], phone_number_id=a["nummer"], customer_phone=a["kunde"], text="Gesperrt", access_token="synthetischer-globaler-ersatz").ok)
        self.webhook(self.paket(a, "account_update", event="ACCOUNT_RECONNECTED"))
        self.webhook(self.rueckmeldung(a, self.sendungen[-1][1]))
        self.assertEqual(len(self.sendungen), anzahl)
        self.assertFalse(verbindungen.verbindungsstatus(a["wid"])["versand_bereit"])
        self.assertEqual(self.kontrolle(b), vorher)
        self.assertEqual(verbindungen.zugang_fuer_werkstatt(b["wid"]).token, b["meta"].token)
        self.assertEqual(b["client"].get(f"/dashboard/whatsapp/medien/{b['bild']}").status_code, 200)
        self.seite("widerrufen", a)

    def test_fremdzugriff_und_signatur_ueber_die_integrierten_routen(self):
        a, b = self.werkstaetten
        for w in self.werkstaetten:
            self.verbinden(w)
            self.synchronisieren(w)
        for bereich, aktion in (("verbinden", "start"), ("synchronisierung", "fortsetzen")):
            r = b["client"].post(f"/dashboard/whatsapp/{bereich}/{aktion}", json={"workshop_id": a["wid"]})
            self.assertEqual(r.status_code, 409)
        self.assertEqual(b["client"].get("/dashboard/whatsapp/verbinden", params={"workshop_id": a["wid"]}).status_code, 403)
        self.assertEqual(b["client"].get(f"/dashboard/whatsapp/medien/{a['bild']}").status_code, 404)
        r = b["client"].get("/dashboard/whatsapp", params={"workshop_id": a["wid"]})
        self.assertEqual(r.status_code, 200)
        # Der vorhandene Posteingang ignoriert den fremden Parameter zugunsten
        # der Sitzungswerkstatt; ein HTTP 200 allein wäre kein Trennungsnachweis.
        self.assertNotIn(a["wid"], r.text)
        self.assertIn(b["wid"], r.text)
        vorher = self.kontrolle(a)
        r = b["client"].post("/dashboard/whatsapp/control", data={"workshop_id": a["wid"], "customer_phone": a["kunde"], "mode": "manual"}, follow_redirects=False)
        self.assertEqual(r.status_code, 303)
        self.assertEqual(self.kontrolle(a), vorher)
        self.assertEqual(self.kontrolle(b)["mode"], "manual")
        for bereich in ("verbinden", "synchronisierung"):
            r = a["client"].post(f"/dashboard/whatsapp/{bereich}/fortsetzen", json={"workshop_id": a["wid"]}, headers={"origin": "https://fremd.invalid"})
            self.assertEqual(r.status_code, 403)
        p = self.paket(a, "messages", messages=[self.nachricht(a, "wamid.signatur")])
        self.webhook(p, erwartet=403, signatur=False)
        self.webhook(p, erwartet=403, signatur="sha256=" + "0" * 64)
        p["entry"][0]["id"] = b["konto"]
        self.assertEqual(self.webhook(p).json()["ignored"], 1)
        self.assertEqual(len(self.nachrichten(a)), 1)
        with db.atomic_database() as conn:
            conn.execute("UPDATE users SET role = 'staff' WHERE email = ?", (a["email"],))
        self.assertEqual(self.post(a, "verbinden", "start").status_code, 303)
        a["client"].cookies.set(SESSION_COOKIE, create_session_token({"email": a["email"], "role": "staff", "workshop_id": a["wid"]}))
        self.assertEqual(self.post(a, "verbinden", "start").status_code, 409)
        self.assertEqual(self.post(a, "synchronisierung", "status").status_code, 409)
        b["client"].cookies.clear()
        self.assertEqual(self.post(b, "verbinden", "start").status_code, 303)

    def test_null_prozent_ablehnung_und_fruehe_rueckmeldung_nach_signup(self):
        a, b = self.werkstaetten
        for w in self.werkstaetten:
            self.verbinden(w)
            self.assertEqual(self.post(w, "synchronisierung", "fortsetzen").status_code, 200)
        self.webhook(self.historie(a, fortschritt=0, nachrichten=[self.nachricht(a, "wamid.null-prozent")]))
        self.seite("laufend", a)
        ablehnung = [{"errors": [{"code": 2593109}]}]
        self.webhook(self.paket(a, "history", history=ablehnung))
        self.assertEqual(sync.status(a["wid"])["schritte"][1]["zustand"], "pruefung")
        self.assertFalse(sync.status(a["wid"])["technisch_bereit"])
        self.assertEqual(len(self.nachrichten(a)), 1)
        self.seite("pruefung", a)
        self.webhook(self.paket(b, "history", history=ablehnung))
        self.assertTrue(sync.status(b["wid"])["technisch_bereit"])
        self.seite("nicht_geteilt", b)
        self.freigabe_nur_im_fixture()
        def frueh(w, mid):
            self.webhook(self.rueckmeldung(w, mid))
            self.webhook(self.echo(w, mid))
        self.fruehe_rueckmeldung = frueh
        p = self.paket(b, "messages", messages=[self.nachricht(b, "wamid.frueh", "Audi A4 2019 120000 km")])
        self.assertEqual(self.webhook(p).json()["processed"], 1)
        self.webhook(p)
        self.assertEqual(len(self.sendungen), 1)
        ausgaenge = [n for n in self.nachrichten(b) if n["direction"] == "outbound"]
        self.assertEqual(len(ausgaenge), 1)
        self.assertEqual(ausgaenge[0]["status"], "read")
        self.assertTrue(json.loads(ausgaenge[0]["payload_json"])["echo_bestaetigt"])
        self.assertEqual(self.kontrolle(b)["mode"], "assistant")
        self.assertTrue(anschluss.automatik_gesperrt(a["wid"]))


class SQLiteAbnahme(AbnahmeFaelle, unittest.TestCase):
    postgres = False


@unittest.skipUnless(os.environ.get("WERKSTATTAI_TEST_POSTGRES_URL"), "Eigene PostgreSQL-Prüfdatenbank erforderlich")
class PostgreSQLAbnahme(AbnahmeFaelle, unittest.TestCase):
    postgres = True
