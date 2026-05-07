from __future__ import annotations


# =========================================================
# Schritte im Intake-Flow
# =========================================================

STEP_FAHRZEUG = "fahrzeug"
STEP_BAUJAHR = "baujahr"
STEP_KILOMETERSTAND = "kilometerstand"
STEP_PROBLEM = "problem"
STEP_FAHRBEREIT = "fahrbereit"
STEP_ABSCHLEPPDIENST = "abschleppdienst"
STEP_FOLLOWUP = "followup"
STEP_TELEFON = "telefon"
STEP_NAME = "name"
STEP_FERTIG = "fertig"
STEP_QUOTE_ANLIEGEN = "quote_anliegen"
STEP_QUOTE_FAHRZEUG = "quote_fahrzeug"
STEP_QUOTE_TELEFON = "quote_telefon"
STEP_QUOTE_NAME = "quote_name"


# =========================================================
# Anfrage-Typen
# =========================================================

REQUEST_TYPE_SERVICE = "service"
REQUEST_TYPE_DIAGNOSE = "diagnose"
REQUEST_TYPE_NOTFALL = "notfall"
REQUEST_TYPE_KOSTENVORANSCHLAG = "kostenvoranschlag"


# =========================================================
# Prioritäten
# =========================================================

PRIORITY_NIEDRIG = "niedrig"
PRIORITY_NORMAL = "normal"
PRIORITY_HOCH = "hoch"


# =========================================================
# Standard-Eingaben
# =========================================================

YES_VALUES = {
    "ja",
    "j",
    "yes",
    "y",
    "klar",
    "ok",
    "okay",
    "natürlich",
    "natuerlich",
    "sicher",
    "genau",
    "passt",
}

NO_VALUES = {
    "nein",
    "n",
    "no",
    "nicht",
    "leider nein",
    "eher nicht",
}

CANCEL_VALUES = {
    "abbrechen",
    "stopp",
    "stop",
    "cancel",
    "ende",
    "zurücksetzen",
    "zuruecksetzen",
    "reset",
    "neu",
    "neu starten",
}

SKIP_VALUES = {
    "überspringen",
    "ueberspringen",
    "skip",
    "egal",
    "nein",
}
