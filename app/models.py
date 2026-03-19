from __future__ import annotations

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Eingabemodell für den /chat Endpoint."""
    session_id: str = Field(..., description="Eindeutige Session-ID (z.B. vom Frontend)")
    message: Optional[str] = Field(None, description="Nachricht des Nutzers; None = Gespräch starten")


class ChatResponse(BaseModel):
    """Ausgabemodell für den /chat Endpoint."""
    reply: str = Field(..., description="Antworttext")
    done: bool = Field(..., description="True, wenn die Datenerfassung abgeschlossen ist")
    data: Dict[str, Any] = Field(default_factory=dict, description="Aktueller Session-Status")


class IntakeState(BaseModel):
    """
    Zustand der Intake-Erfassung.
    Alles bewusst einfach gehalten – später kann das in DB persistiert werden.
    """

    # Flow:
    # fahrzeug -> baujahr -> kilometerstand -> problem
    # -> service: telefon -> name -> fertig
    # -> diagnose/notfall: fahrbereit -> ggf. abschleppdienst -> followup -> telefon -> name -> fertig
    step: str = "fahrzeug"

    # Fahrzeugdaten
    fahrzeug: Optional[str] = None
    baujahr: Optional[str] = None
    kilometerstand: Optional[str] = None  # z.B. "180000"

    # Klassifikation
    request_type: Optional[str] = None  # "service" | "diagnose" | "notfall"
    priority: Optional[str] = None      # "niedrig" | "normal" | "hoch"

    # Status
    fahrbereit: Optional[str] = None       # "ja" / "nein"
    abschleppdienst: Optional[str] = None  # "ja" / "nein" (nur wenn nicht fahrbereit)

    # Problem & Follow-ups
    problem: Optional[str] = None
    followup_questions: List[str] = Field(default_factory=list)
    followup_answers: List[str] = Field(default_factory=list)
    followup_index: int = 0

    # Kontakt
    telefon: Optional[str] = None
    name: Optional[str] = None  # optional

    # Ticket / Meta
    ticket_id: Optional[str] = None
    last_user_message: Optional[str] = None