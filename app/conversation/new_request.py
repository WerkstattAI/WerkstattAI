from __future__ import annotations

from typing import List, Tuple, cast

from app.conversation.analysis import analyze_problem
from app.conversation.intake_fields import consume_intake_fields
from app.conversation.constants import (
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
    extract_km,
    extract_name_candidate,
    extract_phone,
    extract_year,
    infer_fahrbereit_from_text,
    is_cancel_command,
    is_correction,
    is_unavailable_answer,
    strip_request_announcement,
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
    ask_vehicle_after_problem_reply,
    ask_vehicle_clarify_reply,
    build_completion_summary,
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
    return IntakeState(step=STEP_FAHRZEUG, mode="unknown")


def fresh_intake_state_from(state: IntakeState, mode: str = "new") -> IntakeState:
    new_state = reset_state()
    new_state.mode = mode
    new_state.workshop_id = getattr(state, "workshop_id", None)
    return new_state


def is_cancel(text: str) -> bool:
    return is_cancel_command(text)


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


def _continue_after_problem_details(new_state: IntakeState) -> Tuple[IntakeState, str, bool]:
    problem = new_state.problem or ""
    analysis = update_analysis_fields(new_state, problem)

    if analysis["request_type"] == REQUEST_TYPE_SERVICE:
        new_state.followup_questions = []
        new_state.followup_answers = []
        new_state.followup_index = 0
        return _continue_to_contact(new_state, service=True)

    inferred = new_state.fahrbereit or infer_fahrbereit_from_text(problem)
    if inferred:
        new_state.fahrbereit = inferred
        update_analysis_fields(
            new_state,
            problem,
            fahrbereit=new_state.fahrbereit,
            abschleppdienst=getattr(new_state, "abschleppdienst", None),
        )

        if inferred == "nein":
            new_state.step = STEP_ABSCHLEPPDIENST
            return new_state, ask_abschleppdienst_reply(), False

        followups = prepare_followups(new_state, problem)
        if followups:
            new_state.step = STEP_FOLLOWUP
            return new_state, followups[0], False

        return _continue_to_contact(new_state)

    new_state.step = STEP_FAHRBEREIT
    return new_state, ask_fahrbereit_reply(), False


def pending_intake_question(state: IntakeState) -> str:
    questions = {
        STEP_FAHRZEUG: ask_vehicle_clarify_reply,
        STEP_BAUJAHR: ask_baujahr_reply,
        STEP_KILOMETERSTAND: ask_kilometerstand_reply,
        STEP_PROBLEM: ask_problem_reply,
        STEP_FAHRBEREIT: ask_fahrbereit_reply,
        STEP_ABSCHLEPPDIENST: ask_abschleppdienst_reply,
        STEP_TELEFON: ask_phone_reply,
        STEP_NAME: ask_name_reply,
    }
    if state.step == STEP_FOLLOWUP and state.followup_index < len(state.followup_questions):
        return state.followup_questions[state.followup_index]
    return questions.get(state.step, ask_problem_reply)()


def _complete_intake(state: IntakeState) -> Tuple[IntakeState, str, bool]:
    state.step = STEP_FERTIG
    analysis = update_analysis_fields(state, state.problem or "", state.fahrbereit, state.abschleppdienst)
    return state, build_completion_summary(state, analysis["score"]), True


def _continue_to_contact(state: IntakeState, *, service: bool = False) -> Tuple[IntakeState, str, bool]:
    if not state.telefon:
        state.step = STEP_TELEFON
        return state, service_detected_reply() if service else ask_phone_reply(), False
    if state.name:
        return _complete_intake(state)
    state.step = STEP_NAME
    return state, ask_name_reply(), False


def _advance_initial_details(state: IntakeState) -> Tuple[IntakeState, str, bool]:
    for field, step, question in (
        ("fahrzeug", STEP_FAHRZEUG, ask_vehicle_clarify_reply),
        ("baujahr", STEP_BAUJAHR, ask_baujahr_reply),
        ("kilometerstand", STEP_KILOMETERSTAND, ask_kilometerstand_reply),
        ("problem", STEP_PROBLEM, ask_problem_reply),
    ):
        if getattr(state, field) is None:
            state.step = step
            if field == "fahrzeug" and state.problem:
                return state, ask_vehicle_after_problem_reply(state.problem), False
            return state, question(), False
    return _continue_after_problem_details(state)


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
        return fresh_intake_state_from(state, mode="unknown"), "Die Aufnahme ist abgebrochen. Sie können jederzeit ein neues Anliegen melden.", False

    if state.ticket_id or state.step == STEP_FERTIG or (getattr(state, "mode", None) or "unknown").strip().lower() != "new":
        new_state = fresh_intake_state_from(state, mode="new")
    else:
        new_state = copy_state(state)

    new_state.mode = "new"
    new_state.last_user_message = msg

    content, announcement = strip_request_announcement(msg)
    if announcement and not content:
        return new_state, ask_problem_reply(), False

    update = consume_intake_fields(
        new_state, content, vehicle_answer=new_state.step == STEP_FAHRZEUG or is_correction(msg),
    )
    if update.correction:
        if new_state.pending_vehicle_correction:
            return new_state, "Welches Fahrzeug ist richtig? Bitte nennen Sie Marke und Modell.", False
        if new_state.step in {STEP_FAHRZEUG, STEP_BAUJAHR, STEP_KILOMETERSTAND, STEP_PROBLEM}:
            result_state, reply, done = _advance_initial_details(new_state)
        elif new_state.step in {STEP_TELEFON, STEP_NAME}:
            result_state, reply, done = _continue_to_contact(new_state)
        else:
            result_state, reply, done = new_state, pending_intake_question(new_state), False
        prefix = ("Danke, die Angaben sind korrigiert." if update.changed else
                  "Diese Angaben sind bereits gespeichert." if update.recognized else
                  "Welche Angabe soll ich korrigieren?")
        return result_state, prefix + "\n" + reply, done

    if is_unavailable_answer(msg) and new_state.step not in {STEP_NAME, STEP_FOLLOWUP}:
        attempts = new_state.unavailable_attempts.get(new_state.step, 0) + 1
        new_state.unavailable_attempts[new_state.step] = attempts
        hint = {
            STEP_BAUJAHR: "Das Baujahr wird noch benötigt. Sie finden es in den Fahrzeugunterlagen; falls nur die Erstzulassung bekannt ist, nennen Sie diese bitte.",
            STEP_KILOMETERSTAND: "Der Kilometerstand wird noch benötigt. Eine ungefähre Zahl vom Tacho reicht.",
            STEP_FAHRZEUG: "Marke und Modell werden noch benötigt. Beides steht in den Fahrzeugunterlagen.",
            STEP_TELEFON: "Für die Rückmeldung wird eine Telefonnummer benötigt.",
            STEP_FAHRBEREIT: "Bitte Ja oder Nein: Kann das Fahrzeug noch fahren? Wenn Sie unsicher sind, klären Sie das bitte mit der Werkstatt.",
            STEP_ABSCHLEPPDIENST: "Bitte Ja oder Nein: Benötigen Sie einen Abschleppdienst? Bei Unsicherheit wenden Sie sich bitte an die Werkstatt.",
        }.get(new_state.step, "Diese Angabe wird noch benötigt. Beschreiben Sie bitte kurz, was Sie wissen.")
        if attempts == 2:
            hint = "Sie können später hier weitermachen oder mit „abbrechen“ beenden.\n" + hint
        elif attempts > 2:
            hint = "Ich warte auf die fehlende Angabe. Schreiben Sie sie einfach hier, sobald sie vorliegt. Mit „abbrechen“ beenden Sie die Aufnahme."
        return new_state, hint, False

    if new_state.step == STEP_FAHRZEUG:
        return _advance_initial_details(new_state)

    if new_state.step == STEP_BAUJAHR:
        year = new_state.baujahr or extract_year(msg)
        if not year:
            return new_state, ask_baujahr_invalid_reply(), False

        new_state.baujahr = year
        return _advance_initial_details(new_state)

    if new_state.step == STEP_KILOMETERSTAND:
        km = extract_km(msg, expected=True) or new_state.kilometerstand
        if km is None:
            return new_state, ask_kilometerstand_invalid_reply(), False

        new_state.kilometerstand = km

        return _advance_initial_details(new_state)

    if new_state.step == STEP_PROBLEM:
        if len(msg) < 3 or (update.recognized and not new_state.problem):
            return new_state, ask_problem_invalid_reply(), False

        new_state.problem = new_state.problem or content
        return _continue_after_problem_details(new_state)

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

        return _continue_to_contact(new_state)

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

        return _continue_to_contact(new_state)

    if new_state.step == STEP_FOLLOWUP:
        if not msg:
            return new_state, ask_followup_invalid_reply(), False

        early_phone = extract_phone(msg)
        if early_phone:
            new_state.telefon = early_phone
            questions = list(cast(List[str], getattr(new_state, "followup_questions", []) or []))
            idx = int(getattr(new_state, "followup_index", 0) or 0)
            current_question = questions[idx] if idx < len(questions) else None
            if current_question:
                return (
                    new_state,
                    "Danke, die Telefonnummer ist gespeichert.\n"
                    "Bitte beantworten Sie noch kurz diese Frage:\n"
                    f"{current_question}",
                    False,
                )

        answers = list(cast(List[str], getattr(new_state, "followup_answers", []) or []))
        answers.append(msg)
        new_state.followup_answers = answers

        idx = int(getattr(new_state, "followup_index", 0) or 0) + 1
        new_state.followup_index = idx

        questions = list(cast(List[str], getattr(new_state, "followup_questions", []) or []))
        if idx < len(questions):
            return new_state, questions[idx], False

        if getattr(new_state, "telefon", None):
            new_state.step = STEP_NAME
            return new_state, ask_name_reply(), False

        new_state.step = STEP_TELEFON
        return new_state, ask_phone_with_thanks_reply(), False

    if new_state.step == STEP_TELEFON:
        phone = extract_phone(msg)
        if not phone:
            return new_state, ask_phone_invalid_reply(), False

        new_state.telefon = phone
        return _continue_to_contact(new_state)

    if new_state.step == STEP_NAME:
        if lower(msg) in SKIP_VALUES or is_unavailable_answer(msg):
            new_state.name = None
        else:
            new_state.name = extract_name_candidate(msg)
            if not new_state.name:
                return new_state, ask_name_reply(), False

        return _complete_intake(new_state)

    new_state.step = STEP_FAHRZEUG
    return new_state, restart_reply(), False
