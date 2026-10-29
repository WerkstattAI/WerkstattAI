"""Einmalige SMB-App-Anforderung; keine Status-Edge und keine Transportwiederholung."""
import json
import urllib.error
import urllib.request

from app.whatsapp_meta_anschluss import _KeineWeiterleitung


def initialisieren(konfiguration, zugang, art):
    adresse = f"https://graph.facebook.com/{konfiguration.whatsapp_signup_graph_version}/{zugang.phone_number_id}/smb_app_data"
    anfrage = urllib.request.Request(adresse, method="POST",
        headers={"Authorization": "Bearer " + zugang.token, "Content-Type": "application/json", "Accept": "application/json"},
        data=json.dumps({"messaging_product": "whatsapp", "sync_type": art}).encode())
    try:
        with urllib.request.build_opener(_KeineWeiterleitung()).open(anfrage, timeout=15) as antwort:
            inhalt = antwort.read(65537)
        if len(inhalt) > 65536:
            return {"zustand": "unklar"}
        daten = json.loads(inhalt)
        kennung = daten.get("request_id") if isinstance(daten, dict) else None
        if (not isinstance(daten, dict) or daten.get("messaging_product") != "whatsapp" or "error" in daten
                or not isinstance(kennung, str) or not kennung.strip() or len(kennung) > 256):
            return {"zustand": "unklar"}
        return {"zustand": "angenommen", "request_id": kennung}
    except urllib.error.HTTPError as fehler:
        code = None
        try:
            with fehler:
                inhalt = fehler.read(65537)
            if len(inhalt) <= 65536:
                code = json.loads(inhalt).get("error", {}).get("code")
        except Exception:
            pass
        code = code if type(code) is int and 0 <= code <= 2147483647 else None
        zustand = {2593107: "quote", 2593108: "frist", 2593109: "nicht_geteilt"}.get(code,
                    "unklar" if fehler.code >= 500 or fehler.code in (408, 429) else "fehler")
        return {"zustand": zustand, "code": code}
    except (OSError, ValueError, TypeError):
        return {"zustand": "unklar"}
