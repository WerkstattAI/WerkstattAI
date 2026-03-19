from __future__ import annotations

"""
AI-Schicht (Platzhalter).
In Version 1 nutzen wir KEIN echtes AI – aber die Datei ist vorbereitet.

Später:
- OpenAI / lokale LLMs
- Text-Polishing (freundlicher Ton, korrektes Deutsch)
- Intent-Erkennung usw.
"""


def polish_reply_de(text: str) -> str:
    """
    Optionaler Hook, um Antworten später durch ein LLM zu verbessern.
    In v1 geben wir den Text 1:1 zurück.
    """
    return text
