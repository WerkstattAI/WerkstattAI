from __future__ import annotations

from typing import List, Tuple, cast

from app.conversation.analysis import analyze_problem
from app.conversation.constants import (
    CANCEL_VALUES,
    NO_VALUES,
    REQUEST_TYPE_SERVICE,
    SKIP_VALUES,
    STEP_ABSCHLEPPDIENST,
    STEP_BAUJAHR,
    STEP_FAHRBEREIT,
    STEP_FAHRZEUG,
    STEP_FERTIG,
    STEP_FOLLOWUP,
    STEP_KILOMETERSTAND,
    STEP_NAME,
    STEP_PROBLEM,
    STEP_TELEFON,
    YES_VALUES,
)
from app.conversation.extractors import (
    consume_inline_vehicle_year_km,
    extract_km,
    extract_name_candidate,
    extract_phone,
    extract_year,
    infer_fahrbereit_from_text,
    lower,
    normalize,
)
from app.conversation.followups import select_followups
from app.conversation.replies import (
    ask_abschleppdienst_invalid_reply,
    ask_abschleppdienst_reply,
    ask_baujahr_invalid_reply,
    ask_baujahr_reply,
    ask_fahrbereit_invalid_reply,
    ask_fahrbereit_reply,
    ask_followup_invalid_reply,
    ask_kilometerstand_invalid_reply,
    ask_kilometerstand_reply,
    ask_name_reply,
    ask_phone_invalid_reply,
    ask_phone_reply,
    ask_phone_with_thanks_reply,
    ask_problem_invalid_reply,
    ask_problem_reply,
    ask_vehicle_clarify_reply,
    build_completion_summary,
    reset_reply,
    restart_reply,
    service_detected_reply,
    welcome_reply,
)
from app.models import IntakeState


def copy_state(state: IntakeState) -> IntakeState:
    """
    Kompatibel mit Pydantic v1 und v2.
    """
    if hasattr(state, "model_copy"):
        return state.model_copy(deep=True)
    if hasattr(state, "copy"):
        return state.copy(deep=True)
    return state


def reset_state() -> IntakeState:
    return IntakeState(step=STEP_FAHRZEUG)


def is_cancel(text: str) -> bool:
    return lower(text) in CANCEL_VALUES


def is_yes(text: str) -> bool:
    return lower(text) in YES_VALUES


def is_no(text: str) -> bool:
    return lower(text) in NO_VALUES


def update_analysis_fields(
    state: IntakeState,
    problem_text: str,
    fahrbereit: str | None = None,
    abschleppdienst: str | None = None,
) -> dict:
    analysis = analyze_problem(
        problem_text,
        fahrbereit=fahrbereit,
        abschleppdienst=abschleppdienst,
    )

    if hasattr(state, "request_type"):
        state.request_type = analysis["request_type"]

    if hasattr(state, "priority"):
        state.priority = analysis["priority"]

    return analysis


def prepare_followups(
    state: IntakeState,
    problem_text: str,
    include_safety_drive: bool = True,
) -> List[str]:
    followups = select_followups(
        problem_text,
        include_safety_drive=include_safety_drive,
    )
    state.followup_questions = followups
    state.followup_answers = []
    state.followup_index = 0
    return followups


def handle_new_request(state: IntakeState, user_message: str | None) -> Tuple[IntakeState, str, bool]:
    """
    Flow v3:
      fahrzeug
      -> baujahr
      -> kilometerstand
      -> problem
          -> service: telefon -> name -> fertig
          -> diagnose/notfall: fahrbereit -> ggf. abschleppdienst -> followup -> telefon -> name -> fertig
    """

    if user_message is None or normalize(user_message) == "":
        return state, welcome_reply(), False

    msg = normalize(user_message)

    if is_cancel(msg):
        return reset_state(), reset_reply(), False

    new_state = copy_state(state)
    new_state.last_user_message = msg

    if new_state.step == STEP_FAHRZEUG:
        consume_inline_vehicle_year_km(new_state, msg)

        if not getattr(new_state, "fahrzeug", None):
            return new_state, ask_vehicle_clarify_reply(), False

        if not getattr(new_state, "baujahr", None):
            new_state.step = STEP_BAUJAHR
            return new_state, ask_baujahr_reply(new_state.fahrzeug), False

        if not getattr(new_state, "kilometerstand", None):
            new_state.step = STEP_KILOMETERSTAND
            return new_state, ask_kilometerstand_reply(new_state.fahrzeug), False

        new_state.step = STEP_PROBLEM
        return new_state, ask_problem_reply(new_state.fahrzeug), False

    if new_state.step == STEP_BAUJAHR:
        year = extract_year(msg)
        if not year:
            return new_state, ask_baujahr_invalid_reply(), False

        new_state.baujahr = year
        new_state.step = STEP_KILOMETERSTAND
        return new_state, ask_kilometerstand_reply(), False

    if new_state.step == STEP_KILOMETERSTAND:
        km = extract_km(msg)
        if not km:
            return new_state, ask_kilometerstand_invalid_reply(), False

        new_state.kilometerstand = km
        new_state.step = STEP_PROBLEM
        return new_state, ask_problem_reply(), False

    if new_state.step == STEP_PROBLEM:
        if len(msg) < 3:
            return new_state, ask_problem_invalid_reply(), False

        new_state.problem = msg
        analysis = update_analysis_fields(new_state, new_state.problem)

        if analysis["request_type"] == REQUEST_TYPE_SERVICE:
            new_state.followup_questions = []
            new_state.followup_answers = []
            new_state.followup_index = 0
            new_state.step = STEP_TELEFON
            return new_state, service_detected_reply(), False

        inferred = infer_fahrbereit_from_text(new_state.problem)
        if inferred:
            new_state.fahrbereit = inferred
            analysis = update_analysis_fields(
                new_state,
                new_state.problem,
                fahrbereit=new_state.fahrbereit,
                abschleppdienst=getattr(new_state, "abschleppdienst", None),
            )

            if inferred == "nein":
                new_state.step = STEP_ABSCHLEPPDIENST
                return new_state, ask_abschleppdienst_reply(), False

            followups = prepare_followups(new_state, new_state.problem)
            if followups:
                new_state.step = STEP_FOLLOWUP
                return new_state, followups[0], False

            new_state.step = STEP_TELEFON
            return new_state, ask_phone_reply(), False

        new_state.step = STEP_FAHRBEREIT
        return new_state, ask_fahrbereit_reply(), False

    if new_state.step == STEP_FAHRBEREIT:
        inferred = infer_fahrbereit_from_text(msg)

        if inferred is None and not (is_yes(msg) or is_no(msg)):
            return new_state, ask_fahrbereit_invalid_reply(), False

        new_state.fahrbereit = inferred or ("ja" if is_yes(msg) else "nein")
        update_analysis_fields(
            new_state,
            new_state.problem or "",
            fahrbereit=new_state.fahrbereit,
            abschleppdienst=getattr(new_state, "abschleppdienst", None),
        )

        if new_state.fahrbereit == "nein":
            new_state.step = STEP_ABSCHLEPPDIENST
            return new_state, ask_abschleppdienst_reply(), False

        followups = prepare_followups(new_state, new_state.problem or "")
        if followups:
            new_state.step = STEP_FOLLOWUP
            return new_state, followups[0], False

        new_state.step = STEP_TELEFON
        return new_state, ask_phone_reply(), False

    if new_state.step == STEP_ABSCHLEPPDIENST:
        if not (is_yes(msg) or is_no(msg)):
            return new_state, ask_abschleppdienst_invalid_reply(), False

        new_state.abschleppdienst = "ja" if is_yes(msg) else "nein"
        update_analysis_fields(
            new_state,
            new_state.problem or "",
            fahrbereit=getattr(new_state, "fahrbereit", None),
            abschleppdienst=new_state.abschleppdienst,
        )

        followups = prepare_followups(
            new_state,
            new_state.problem or "",
            include_safety_drive=False,
        )
        if followups:
            new_state.step = STEP_FOLLOWUP
            return new_state, followups[0], False

        new_state.step = STEP_TELEFON
        return new_state, ask_phone_with_thanks_reply(), False

    if new_state.step == STEP_FOLLOWUP:
        if not msg:
            return new_state, ask_followup_invalid_reply(), False

        answers = list(cast(List[str], getattr(new_state, "followup_answers", []) or []))
        answers.append(msg)
        new_state.followup_answers = answers

        idx = int(getattr(new_state, "followup_index", 0) or 0) + 1
        new_state.followup_index = idx

        questions = list(cast(List[str], getattr(new_state, "followup_questions", []) or []))
        if idx < len(questions):
            return new_state, questions[idx], False

        new_state.step = STEP_TELEFON
        return new_state, ask_phone_with_thanks_reply(), False

    if new_state.step == STEP_TELEFON:
        phone = extract_phone(msg)
        if not phone:
            return new_state, ask_phone_invalid_reply(), False

        new_state.telefon = phone
        new_state.step = STEP_NAME
        return new_state, ask_name_reply(), False

    if new_state.step == STEP_NAME:
        if lower(msg) in SKIP_VALUES:
            new_state.name = None
        else:
            new_state.name = extract_name_candidate(msg)

        new_state.step = STEP_FERTIG
        analysis = update_analysis_fields(
            new_state,
            new_state.problem or "",
            fahrbereit=getattr(new_state, "fahrbereit", None),
            abschleppdienst=getattr(new_state, "abschleppdienst", None),
        )

        reply = build_completion_summary(new_state, analysis["score"])
        return new_state, reply, True

    new_state.step = STEP_FAHRZEUG
    return new_state, restart_reply(), False