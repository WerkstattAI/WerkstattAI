from __future__ import annotations

from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field, ConfigDict
from app.security_config import MAX_MESSAGE_LENGTH, MAX_ID_LENGTH, MAX_PHONE_LENGTH


class ChatRequest(BaseModel):
    """Eingabemodell für den /chat Endpoint."""
    model_config = ConfigDict(extra="forbid")
    workshop_id: Optional[str] = Field(None, max_length=MAX_ID_LENGTH, description="Werkstatt-ID fuer Multi-Tenant-Betrieb")
    session_id: str = Field(..., min_length=1, max_length=MAX_ID_LENGTH, pattern=r"\S", description="Eindeutige Session-ID")
    message: Optional[str] = Field(None, max_length=MAX_MESSAGE_LENGTH, description="Nachricht; None startet das Gespräch")
    channel: Literal["web_chat"] = "web_chat"
    phone: Optional[str] = Field(None, max_length=MAX_PHONE_LENGTH)


class ChatResponse(BaseModel):
    """Ausgabemodell für den /chat Endpoint."""
    reply: str = Field(..., description="Antworttext")
    done: bool = Field(..., description="True, wenn die Datenerfassung abgeschlossen ist")
    data: Dict[str, Any] = Field(default_factory=dict, description="Aktueller Session-Status")


class WhatsAppWebhookRequest(BaseModel):
    """Testformat fuer eingehende WhatsApp-Nachrichten."""
    workshop_id: Optional[str] = Field(None, max_length=MAX_ID_LENGTH, description="Werkstatt-ID fuer Multi-Tenant-Betrieb")
    from_phone: str = Field(..., alias="from", min_length=1, max_length=MAX_PHONE_LENGTH, description="Telefonnummer des WhatsApp-Nutzers")
    text: Optional[str] = Field(None, max_length=MAX_MESSAGE_LENGTH, description="Text der eingehenden Nachricht")


class WhatsAppWebhookResponse(BaseModel):
    """Antwortformat fuer den WhatsApp-Testwebhook."""
    reply: str
    done: bool
    session_id: str
    workshop_id: str
    channel: str = "whatsapp"
    data: Dict[str, Any] = Field(default_factory=dict)


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

    mode: str = "unknown"  # "unknown" | "new" | "existing" | "general"

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
    workshop_id: Optional[str] = None
    ticket_id: Optional[str] = None
    source: Optional[str] = None
    last_user_message: Optional[str] = None
