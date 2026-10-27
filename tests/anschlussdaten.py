"""Synthetischer HTTP-Transport für die echte lokale Anschlusskette."""
import io
import json
from urllib.parse import parse_qs, urlsplit

import app.db as db


class MetaSimulation:
    def __init__(self):
        self.token = "synthetischer-anschluss-zugang"
        self.abonniert = False
        self.aufrufe = []
        self.antworten = {}
        self.vor_aufruf = None
        self.debug = {"is_valid": True, "app_id": "111", "expires_at": 0, "data_access_expires_at": 0,
            "scopes": ["whatsapp_business_management", "whatsapp_business_messaging"],
            "granular_scopes": [{"scope": "whatsapp_business_management", "target_ids": ["333"]}]}
        self.nummern = [{"id": "444"}]
        self.nummer = {"id": "444", "display_phone_number": "+49 000 123", "is_on_biz_app": True, "platform_type": "CLOUD_API"}

    def open(self, anfrage, *args, **kwargs):
        assert db._TRANSACTION_CONNECTION.get() is None, "HTTP darf keine Datenbanksperre halten"
        url = urlsplit(anfrage.full_url)
        assert url.scheme == "https" and url.netloc == "graph.facebook.com"
        pfad = url.path.removeprefix("/v26.0/")
        methode = anfrage.get_method()
        self.aufrufe.append((methode, pfad))
        if self.vor_aufruf:
            self.vor_aufruf(methode, pfad)
        if (methode, pfad) in self.antworten:
            daten = self.antworten[(methode, pfad)]
            if isinstance(daten, Exception):
                raise daten
        elif pfad == "oauth/access_token":
            assert parse_qs(url.query)["code"][0].startswith("synthetischer-einmalcode")
            daten = {"access_token": self.token}
        elif pfad == "debug_token":
            daten = {"data": self.debug}
        elif pfad == "333/phone_numbers":
            daten = {"data": self.nummern}
        elif pfad == "444":
            daten = self.nummer
        elif pfad == "333/subscribed_apps":
            if methode == "POST":
                self.abonniert = True
                daten = {"success": True}
            else:
                daten = {"data": [{"whatsapp_business_api_data": {"id": "111"}}] if self.abonniert else []}
        else:
            raise AssertionError("Nicht simulierter Meta-Pfad")
        return io.BytesIO(json.dumps(daten).encode())
