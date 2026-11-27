"""Adaptive question router (module M6).

Router and service tests use a synthetic regulation database in a temporary
directory; API tests sign in real accounts through the login service. No model
is called: answer generation is replaced by a recording stand-in, and the real
Gemini entry point is patched to fail if reached.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import workflow
from app.database import init_database, insert_regulation_with_pages
from app.models import GroundedAnswer, GroundedCitation
from backend.app.api.v1 import query as query_routes
from backend.app.auth.models import ROLE_ADMINISTRATOR, ROLE_STUDENT
from backend.app.main import app
from backend.app.schemas.routing import CLAUSE_LOOKUP_TOP_K, RouteDecision
from backend.app.services import adaptive_router, query_service
from backend.app.services.adaptive_router import (
    DEFAULT_MIN_RETRIEVAL_SCORE,
    MIN_SCORE_ENV,
    configured_min_score,
    detect_clause_reference,
    has_regulation_terms,
    route_question,
)
from backend.tests.auth_support import create_signed_in_account, make_auth_settings, use_auth_database

BATCH, PROGRAMME = "2023", "CSE"
CRICKET = "Who won the cricket world cup in 2011?"
THEORY_QUESTION = "What marks are required to pass a theory course?"

PAGES = [
    "10.1 Attendance: students need seventy five percent attendance to sit the end semester examinations.",
    # The answer page for THEORY_QUESTION ...
    "11.1 Theory: a student is declared successful with forty percent in the end examination and fifty percent overall.",
    # ... and a page that outranks it (mirrors the genuine miss in the retrieval report).
    "Mandatory courses: the pass mark is fifty percent. Marks required to pass a mandatory course are recorded per course.",
    "14.3 Honours degree: a CGPA of not less than eight is required, with every course passed at the first appearance.",
    *[f"Campus note {n}: the library opens at {n} and wardens record visitors in register {n}{n}." for n in range(1, 23)],
]


def _seed(db_path: Path, pages: list[str], *, batch: str = BATCH, name: str = "Rulebook", status: str = "approved") -> None:
    init_database(db_path)
    insert_regulation_with_pages(
        {
            "document_name": name, "regulation_version": "2023", "effective_date": "2023-06-01",
            "applicable_batches": [batch], "applicable_programmes": [PROGRAMME], "upload_date": "2023-06-01",
            "total_pages": len(pages), "processing_status": "extracted", "verification_status": status,
        },
        [{"page_number": n, "extracted_text": text, "extraction_status": "success"} for n, text in enumerate(pages, 1)],
        db_path=db_path,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "router.db"
    _seed(path, PAGES)
    return path


@pytest.fixture(autouse=True)
def _gemini_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**_: Any) -> Any:
        raise AssertionError("The real answer-generation model must never be called in these tests.")

    monkeypatch.setattr(workflow, "generate_grounded_answer", forbidden)
    monkeypatch.delenv(MIN_SCORE_ENV, raising=False)


class RecordingGenerator:
    """Stand-in for the Gemini service that records the evidence it receives."""

    def __init__(self) -> None:
        self.calls: list[list[dict[str, Any]]] = []

    def generate_grounded_answer(self, *, evidence_chunks: list[dict[str, Any]], **_: Any) -> GroundedAnswer:
        self.calls.append(list(evidence_chunks))
        first = evidence_chunks[0]
        return GroundedAnswer(
            answer="Grounded test answer.",
            status="answered",
            citations=[
                GroundedCitation(
                    document_name=first["document_name"],
                    regulation_version=first["regulation_version"],
                    page_number=first["page_number"],
                    chunk_id=first["chunk_id"],
                    relevant_supporting_text=str(first["chunk_text"])[:40],
                )
            ],
            limitations=None,
        )


def _no_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(**_: Any) -> Any:
        raise AssertionError("This route must not retrieve.")

    monkeypatch.setattr(workflow, "build_retrieval_corpus_for_cohort", forbidden)


# --------------------------------------------------------------------------- #
# Signals
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("question", "clause"),
    [
        ("What does clause 10.1 say?", "10.1"),
        ("Explain Clause 14.3.", "14.3"),
        ("Summarise section 12.2.2 please", "12.2.2"),
        ("what is in cl. 7.15", "7.15"),
        ("Clause No. 10(a)", "10(a)"),
        ("What is the attendance needed?", None),
        ("Can I write the exam with 70.5% attendance?", None),
    ],
)
def test_clause_references_are_detected(question: str, clause: str | None) -> None:
    assert detect_clause_reference(question) == clause


@pytest.mark.parametrize(
    ("question", "in_scope"),
    [
        (CRICKET, False),
        ("What is the weather in Chennai today?", False),
        ("Tell me a joke", False),
        ("", False),
        (THEORY_QUESTION, True),
        ("revaluation rules", True),
        ("How many arrears can I have?", True),
        ("What about withdrawals?", True),  # only the singular "withdrawal" is listed
        ("What CGPA is needed for honours?", True),
    ],
)
def test_regulation_vocabulary(question: str, in_scope: bool) -> None:
    assert has_regulation_terms(question) is in_scope


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, DEFAULT_MIN_RETRIEVAL_SCORE), ("", DEFAULT_MIN_RETRIEVAL_SCORE), ("  ", DEFAULT_MIN_RETRIEVAL_SCORE),
     ("4.5", 4.5), (" 0 ", 0.0)],
)
def test_min_score_configuration(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: float) -> None:
    if raw is not None:
        monkeypatch.setenv(MIN_SCORE_ENV, raw)
    assert configured_min_score() == expected


@pytest.mark.parametrize("raw", ["abc", "-1", "nan", "inf", "-inf"])
def test_invalid_min_score_configuration_is_rejected(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv(MIN_SCORE_ENV, raw)
    with pytest.raises(ValueError, match=MIN_SCORE_ENV):
        configured_min_score()


# --------------------------------------------------------------------------- #
# RouteDecision validation
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fields",
    [
        {"route": "general", "reason": "missing_cohort", "top_k": 5},  # reason from another route
        {"route": "out_of_scope", "reason": "no_regulation_terms", "top_k": 5},  # no retrieval details allowed
        {"route": "clarify", "reason": "missing_cohort", "best_score": 1.0},
        {"route": "clause_lookup", "reason": "clause_reference", "top_k": 3},  # no clause number
        {"route": "clause_lookup", "reason": "clause_reference", "clause_number": "10.1", "top_k": 5},  # not top 3
        {"route": "low_evidence", "reason": "clause_not_found", "top_k": 3},
        {"route": "general", "reason": "evidence_found"},  # no top_k
        {"route": "general", "reason": "evidence_found", "top_k": 5, "best_score": 1.0, "min_score": 3.0,
         "threshold_applied": True},  # below the threshold but routed general
        {"route": "low_evidence", "reason": "score_below_threshold", "top_k": 5, "best_score": 4.0, "min_score": 3.0,
         "threshold_applied": True},  # above the threshold
        {"route": "low_evidence", "reason": "score_below_threshold", "top_k": 5},  # threshold not applied
        {"route": "general", "reason": "evidence_found", "top_k": 5, "threshold_applied": True},
        {"route": "general", "reason": "evidence_found", "top_k": 5, "extra": 1},
        {"route": "maybe", "reason": "evidence_found", "top_k": 5},
    ],
)
def test_inconsistent_route_decisions_are_rejected(fields: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RouteDecision(**fields)


def test_only_answering_routes_may_call_the_generator() -> None:
    assert RouteDecision(route="general", reason="evidence_found", top_k=5).calls_generator
    assert RouteDecision(route="clause_lookup", reason="clause_reference", clause_number="1.1", top_k=3).calls_generator
    assert not RouteDecision(route="out_of_scope", reason="no_regulation_terms").calls_generator
    assert not RouteDecision(route="clarify", reason="missing_cohort").calls_generator
    assert not RouteDecision(route="low_evidence", reason="no_applicable_regulations").calls_generator


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #


def test_cricket_question_is_refused_without_retrieval(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_corpus(monkeypatch)

    decision = route_question(CRICKET, BATCH, PROGRAMME, db_path=db_path).decision

    assert (decision.route, decision.reason) == ("out_of_scope", "no_regulation_terms")
    assert decision.best_score is None and decision.top_k is None


def test_out_of_scope_is_checked_before_the_cohort(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _no_corpus(monkeypatch)
    assert route_question(CRICKET, "", "", db_path=db_path).decision.route == "out_of_scope"


@pytest.mark.parametrize(("batch", "programme"), [("", PROGRAMME), (BATCH, ""), ("  ", " "), (None, None)])
def test_missing_cohort_asks_for_clarification_without_retrieval(
    db_path: Path, monkeypatch: pytest.MonkeyPatch, batch: Any, programme: Any
) -> None:
    _no_corpus(monkeypatch)

    decision = route_question("What attendance is needed?", batch, programme, db_path=db_path).decision

    assert (decision.route, decision.reason) == ("clarify", "missing_cohort")


def test_clause_lookup_uses_the_filtered_bm25_path_with_top_3(db_path: Path) -> None:
    outcome = route_question("What does clause 10.1 say?", BATCH, PROGRAMME, db_path=db_path, top_k=8)

    decision = outcome.decision
    assert (decision.route, decision.clause_number, decision.top_k) == ("clause_lookup", "10.1", CLAUSE_LOOKUP_TOP_K)
    assert decision.threshold_applied is False  # a verified clause is the evidence
    results = outcome.retrieval["results"]
    assert len(results) == CLAUSE_LOOKUP_TOP_K
    assert results[0]["page_number"] == 1


def test_missing_clause_abstains(db_path: Path) -> None:
    decision = route_question("What does clause 99.9 say?", BATCH, PROGRAMME, db_path=db_path).decision

    assert (decision.route, decision.reason, decision.clause_number) == ("low_evidence", "clause_not_found", "99.9")


def test_cohort_without_regulations_abstains(db_path: Path) -> None:
    decision = route_question("What attendance is needed?", "2019", PROGRAMME, db_path=db_path).decision

    assert (decision.route, decision.reason) == ("low_evidence", "no_applicable_regulations")


def test_pending_regulations_are_never_used(tmp_path: Path) -> None:
    path = tmp_path / "pending.db"
    _seed(path, PAGES, status="pending")

    decision = route_question("What attendance is needed?", BATCH, PROGRAMME, db_path=path).decision

    assert (decision.route, decision.reason) == ("low_evidence", "no_applicable_regulations")


def test_weak_evidence_below_the_threshold_abstains(db_path: Path) -> None:
    decision = route_question("Can the honours syllabus change?", BATCH, PROGRAMME, db_path=db_path).decision

    assert (decision.route, decision.reason) == ("low_evidence", "score_below_threshold")
    assert decision.threshold_applied and decision.best_score < decision.min_score == DEFAULT_MIN_RETRIEVAL_SCORE


def test_threshold_is_configurable(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    question = "What attendance is needed to sit the examinations?"
    best = route_question(question, BATCH, PROGRAMME, db_path=db_path).decision.best_score

    assert route_question(question, BATCH, PROGRAMME, db_path=db_path, min_score=best + 0.01).decision.route == "low_evidence"
    assert route_question(question, BATCH, PROGRAMME, db_path=db_path, min_score=best).decision.route == "general"
    monkeypatch.setenv(MIN_SCORE_ENV, str(best + 1))
    assert route_question(question, BATCH, PROGRAMME, db_path=db_path).decision.reason == "score_below_threshold"
    with pytest.raises(ValueError):
        route_question(question, BATCH, PROGRAMME, db_path=db_path, min_score=-1)
    with pytest.raises(ValueError):
        route_question(question, BATCH, PROGRAMME, db_path=db_path, min_score=math.nan)


def test_genuine_retrieval_miss_is_still_routed_general(db_path: Path) -> None:
    """Mirrors the miss in the retrieval report: a generic pass-mark page outranks the theory page.

    Routing does not hide ranking errors; the question is in scope and well above the threshold.
    """
    outcome = route_question(THEORY_QUESTION, BATCH, PROGRAMME, db_path=db_path)

    assert (outcome.decision.route, outcome.decision.reason) == ("general", "evidence_found")
    assert outcome.decision.best_score >= outcome.decision.min_score
    assert outcome.retrieval["results"][0]["page_number"] == 3  # the mandatory-course page, not page 2


def test_small_corpora_skip_the_threshold(tmp_path: Path) -> None:
    """In a one-page corpus BM25 scores a matching term below zero, so the threshold is not applied."""
    path = tmp_path / "tiny.db"
    _seed(path, ["Attendance: students need seventy five percent attendance to sit examinations."])

    decision = route_question("What attendance is needed?", BATCH, PROGRAMME, db_path=path).decision

    assert decision.best_score < DEFAULT_MIN_RETRIEVAL_SCORE
    assert (decision.route, decision.threshold_applied) == ("general", False)


# --------------------------------------------------------------------------- #
# Service: answer, abstain, clarify or refuse
# --------------------------------------------------------------------------- #


def _answer(db_path: Path, question: str, batch: str | None = BATCH, programme: str | None = PROGRAMME,
            **kwargs: Any) -> tuple[dict[str, Any], RecordingGenerator]:
    generator = RecordingGenerator()
    result = query_service.answer_with_adaptive_routing(
        batch, programme, question, db_path=db_path, gemini_service=generator, **kwargs
    )
    return result, generator


def test_general_questions_use_the_existing_answer_path(db_path: Path) -> None:
    result, generator = _answer(db_path, "What attendance is needed to sit the examinations?")

    assert result["route"]["route"] == "general"
    assert result["status"] == "answered"
    assert len(generator.calls) == 1 and len(generator.calls[0]) == 5
    assert result["citations"] and result["citations"][0]["page_number"] == 1  # validated against retrieved evidence
    assert all(chunk["document_name"] == "Rulebook" for chunk in generator.calls[0])


def test_clause_lookup_answers_from_the_top_3_chunks(db_path: Path) -> None:
    result, generator = _answer(db_path, "What does clause 14.3 say?", top_k=10)

    assert result["route"]["route"] == "clause_lookup"
    assert len(generator.calls) == 1 and len(generator.calls[0]) == CLAUSE_LOOKUP_TOP_K
    assert len(result["retrieval"]["results"]) == CLAUSE_LOOKUP_TOP_K
    assert generator.calls[0][0]["page_number"] == 4


@pytest.mark.parametrize(
    ("question", "batch", "route", "reason", "retrieval_status"),
    [
        (CRICKET, BATCH, "out_of_scope", "no_regulation_terms", "skipped"),
        ("What attendance is needed?", "", "clarify", "missing_cohort", "skipped"),
        ("What does clause 99.9 say?", BATCH, "low_evidence", "clause_not_found", "no_evidence"),
        ("Can the honours syllabus change?", BATCH, "low_evidence", "score_below_threshold", "no_evidence"),
        ("What attendance is needed?", "2019", "low_evidence", "no_applicable_regulations", "no_evidence"),
    ],
)
def test_non_answering_routes_never_call_the_generator(
    db_path: Path, question: str, batch: str, route: str, reason: str, retrieval_status: str
) -> None:
    result, generator = _answer(db_path, question, batch=batch)

    assert generator.calls == []
    assert (result["route"]["route"], result["route"]["reason"]) == (route, reason)
    assert result["status"] == "insufficient_evidence"
    assert result["citations"] == [] and result["answer"]["citations"] == []
    assert result["retrieval"]["status"] == retrieval_status and result["retrieval"]["results"] == []


def test_clarification_asks_for_the_cohort(db_path: Path) -> None:
    result, _ = _answer(db_path, "What attendance is needed?", batch="")
    assert "admission batch and programme" in result["answer"]["answer"]


def test_supplied_evidence_still_bypasses_routing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The existing delegation entry point is unchanged."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(workflow, "answer_student_question", lambda **kwargs: calls.append(kwargs) or {"status": "ok"})
    monkeypatch.setattr(adaptive_router, "route_question", lambda *a, **k: pytest.fail("must not route"))

    assert query_service.answer_student_regulation_question("2023", "CSE", CRICKET, evidence_chunks=[{"x": 1}]) == {"status": "ok"}
    assert calls[0]["question"] == CRICKET


# --------------------------------------------------------------------------- #
# API
# --------------------------------------------------------------------------- #


@pytest.fixture
def api(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Any, Any, list[int]]]:
    settings = make_auth_settings()
    use_auth_database(app, monkeypatch, db_path, settings)
    monkeypatch.setitem(app.dependency_overrides, query_routes.get_db_path, lambda: str(db_path))
    generated: list[int] = []

    def fake_generate(**kwargs: Any) -> GroundedAnswer:
        generated.append(len(kwargs["evidence_chunks"]))
        return RecordingGenerator().generate_grounded_answer(**kwargs)

    monkeypatch.setattr(workflow, "generate_grounded_answer", fake_generate)
    student = create_signed_in_account(db_path, settings, ROLE_STUDENT, admission_batch=BATCH, programme=PROGRAMME)
    admin = create_signed_in_account(db_path, settings, ROLE_ADMINISTRATOR)
    yield TestClient(app), student, admin, generated


def _ask(client: TestClient, who: Any, question: str, batch: str = BATCH, **extra: Any) -> Any:
    body = {"question": question, "admission_batch": batch, "programme": PROGRAMME, **extra}
    return client.post("/api/v1/query/ask", json=body, headers=who.headers)


def test_api_refuses_the_cricket_question_without_generation(api: tuple[TestClient, Any, Any, list[int]]) -> None:
    client, student, _, generated = api

    response = _ask(client, student, CRICKET)

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == {
        "route": "out_of_scope", "reason": "no_regulation_terms", "clause_number": None, "top_k": None,
        "best_score": None, "min_score": None, "threshold_applied": False,
    }
    assert body["status"] == "insufficient_evidence" and body["citations"] == []
    assert generated == []


def test_api_answers_clause_lookups_from_three_chunks(api: tuple[TestClient, Any, Any, list[int]]) -> None:
    client, student, _, generated = api

    response = _ask(client, student, "What does clause 10.1 say?", top_k=10)

    assert response.status_code == 200
    assert response.json()["route"]["route"] == "clause_lookup"
    assert generated == [CLAUSE_LOOKUP_TOP_K]
    assert len(response.json()["retrieval"]["results"]) == CLAUSE_LOOKUP_TOP_K


def test_api_abstains_on_weak_evidence(api: tuple[TestClient, Any, Any, list[int]]) -> None:
    client, _, admin, generated = api

    response = _ask(client, admin, "Can the honours syllabus change?")

    assert response.json()["route"]["reason"] == "score_below_threshold"
    assert generated == []


def test_api_cohort_authorization_runs_before_routing(
    api: tuple[TestClient, Any, Any, list[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, student, _, generated = api
    monkeypatch.setattr(adaptive_router, "route_question", lambda *a, **k: pytest.fail("must not route"))

    response = _ask(client, student, "What attendance is needed?", batch="2019")

    assert response.status_code == 403
    assert generated == []


def test_api_blank_cohort_is_still_rejected_with_400(api: tuple[TestClient, Any, Any, list[int]]) -> None:
    client, _, admin, _ = api
    assert _ask(client, admin, "What attendance is needed?", batch="  ").status_code == 400


def test_api_invalid_threshold_configuration_fails_safely(
    api: tuple[TestClient, Any, Any, list[int]], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, student, _, generated = api
    monkeypatch.setenv(MIN_SCORE_ENV, "not-a-number")

    response = _ask(client, student, "What attendance is needed to sit the examinations?")

    assert response.status_code == 500
    assert response.json() == {"detail": query_routes.QUERY_INTERNAL_ERROR_DETAIL}
    assert generated == []
