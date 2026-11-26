"""Public response shape of ``POST /api/v1/query/ask`` (Part 3.10).

The API returns only ``status``, ``answer``, ``citations``, ``validation_issues``
and ``retrieval`` (status, message and per-chunk source metadata). The internal
workflow result keeps the full retrieval ``corpus`` for the pipeline and the
Streamlit application, but it, raw chunk text and any other undeclared internal
field must never reach API clients.

All tests use temporary databases; Gemini is always replaced by a test double.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from app import workflow
from app.database import init_database, insert_regulation_with_pages
from app.models import GroundedAnswer, GroundedCitation
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.main import app
from backend.tests.auth_support import sign_in_module_clients_as_administrator


@pytest.fixture(autouse=True)
def _signed_in_as_administrator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The endpoints exercised here require an administrator since Stage 4.

    Every client this module creates sends the token of a real administrator
    account created for the test (see ``backend/tests/auth_support.py``).
    """
    sign_in_module_clients_as_administrator(sys.modules[__name__], app, tmp_path, monkeypatch)


ASK_URL = "/api/v1/query/ask"
BATCH = "2024"
PROGRAMME = "BSc CS"
QUESTION = "What is the minimum attendance requirement?"

PUBLIC_KEYS = {"status", "answer", "citations", "validation_issues", "retrieval"}
PUBLIC_RETRIEVAL_KEYS = {"status", "message", "results"}
PUBLIC_RESULT_KEYS = {
    "chunk_id",
    "regulation_id",
    "document_name",
    "regulation_version",
    "page_number",
    "admission_batch",
    "programme",
    "retrieval_score",
}
PUBLIC_CITATION_KEYS = {"document_name", "regulation_version", "page_number", "chunk_id", "relevant_supporting_text"}
INTERNAL_KEYS = {
    "corpus",
    "chunks",
    "regulations",
    "chunk_text",
    "chunk text",
    "verification_status",
    "applicable_batches",
    "applicable_programmes",
    "admission batch applicability",
    "programme applicability",
    "chunking_strategy",
    "chunking strategy",
    "pages_loaded",
    "chunks_created",
    "page_load_error",
}

CITED_QUOTE = "minimum of 75 percent attendance in each course"
UNCITED_MARKER = "UNCITED-MARKER-7c2e library fines are waived on public holidays"


# --------------------------------------------------------------------------- #
# Fixtures and helpers
# --------------------------------------------------------------------------- #


def _seed(
    db_path: Path,
    *,
    name: str,
    version: str,
    pages: list[str],
    batch: str = BATCH,
    status: str = "approved",
) -> int:
    return insert_regulation_with_pages(
        {
            "document_name": name,
            "regulation_version": version,
            "effective_date": "2024-08-01",
            "applicable_batches": [batch],
            "applicable_programmes": [PROGRAMME],
            "upload_date": "2024-07-01",
            "total_pages": len(pages),
            "verification_status": status,
        },
        [{"page_number": i, "text": text, "status": "success"} for i, text in enumerate(pages, start=1)],
        db_path=db_path,
    )


class Env:
    def __init__(self, client: TestClient, db_path: Path) -> None:
        self.client = client
        self.db_path = db_path
        self.responder: Callable[..., GroundedAnswer] = _cite_quote
        self.generation_calls: list[dict[str, Any]] = []

    def ask(self, **overrides: Any) -> dict[str, Any]:
        response = self.client.post(
            ASK_URL, json={"question": QUESTION, "admission_batch": BATCH, "programme": PROGRAMME, **overrides}
        )
        assert response.status_code == 200, response.text
        return response.json()

    def raw(self, **overrides: Any):
        return self.client.post(
            ASK_URL, json={"question": QUESTION, "admission_batch": BATCH, "programme": PROGRAMME, **overrides}
        )


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Env]:
    db_path = tmp_path / "response_shape.db"
    init_database(db_path)
    _seed(
        db_path,
        name="R2024 Academic Regulations",
        version="R2024",
        pages=[
            f"Section 4.2 Attendance. Every student must maintain a {CITED_QUOTE} to sit examinations.",
            f"Section 9.9 Library. {UNCITED_MARKER}.",
            "Section 7.1 Grading. A minimum grade point of 5.0 is required to pass a course.",
        ],
    )
    # A cohort whose only approved regulation has no retrievable text.
    _seed(db_path, name="Blank Regulation", version="R2023", pages=["   ", ""], batch="2023")

    environment = Env(TestClient(app), db_path)

    def generation(**kwargs: Any) -> GroundedAnswer:
        environment.generation_calls.append(kwargs)
        return environment.responder(**kwargs)

    monkeypatch.setattr("app.workflow.generate_grounded_answer", generation)
    app.dependency_overrides[query_routes.get_db_path] = lambda: str(db_path)
    app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(db_path)
    try:
        yield environment
    finally:
        app.dependency_overrides.pop(query_routes.get_db_path, None)
        app.dependency_overrides.pop(regulation_routes.get_db_path, None)


def _chunk_with(evidence: list[dict[str, Any]], text: str) -> dict[str, Any]:
    for chunk in evidence:
        if text in str(chunk.get("chunk_text", "")):
            return chunk
    raise AssertionError(f"No evidence chunk contains {text!r}")


def _cite_quote(**kwargs: Any) -> GroundedAnswer:
    chunk = _chunk_with(list(kwargs["evidence_chunks"]), CITED_QUOTE)
    return GroundedAnswer(
        answer="Students must maintain a minimum of 75 percent attendance in each course.",
        status="answered",
        citations=[GroundedCitation(chunk_id=str(chunk["chunk_id"]), relevant_supporting_text=CITED_QUOTE)],
    )


def _conflicting(**kwargs: Any) -> GroundedAnswer:
    return _cite_quote(**kwargs).model_copy(update={"status": "conflicting_evidence"})


def _failing(**_kwargs: Any) -> GroundedAnswer:
    raise RuntimeError("simulated Gemini outage")


def _fabricated(**_kwargs: Any) -> GroundedAnswer:
    return GroundedAnswer(
        answer="Students need only 10 percent attendance.",
        status="answered",
        citations=[GroundedCitation(chunk_id="invented-chunk-99", relevant_supporting_text="10 percent attendance")],
    )


def _all_keys(value: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(str(key))
            keys |= _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_keys(item)
    return keys


def _assert_public_shape(body: dict[str, Any]) -> None:
    assert set(body) == PUBLIC_KEYS
    assert set(body["retrieval"]) == PUBLIC_RETRIEVAL_KEYS
    for item in body["retrieval"]["results"]:
        assert set(item) <= PUBLIC_RESULT_KEYS, set(item) - PUBLIC_RESULT_KEYS
    for citation in body["citations"]:
        assert set(citation) == PUBLIC_CITATION_KEYS
    leaked = _all_keys(body) & INTERNAL_KEYS
    assert not leaked, f"Internal fields leaked: {leaked}"


# --------------------------------------------------------------------------- #
# A/B/C. Exact public shape on every response path
# --------------------------------------------------------------------------- #


def _setup_answered(env: Env, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return {}


def _setup_conflicting(env: Env, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    env.responder = _conflicting
    return {}


def _setup_no_cohort_match(env: Env, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return {"admission_batch": "2019"}


def _setup_no_evidence(env: Env, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    return {"admission_batch": "2023"}


def _setup_corpus_failure(env: Env, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    def failing_lookup(*_args: Any, **_kwargs: Any) -> Any:
        raise sqlite3.OperationalError("simulated database failure")

    monkeypatch.setattr("app.workflow.get_applicable_regulations", failing_lookup)
    return {}


def _setup_gemini_failure(env: Env, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    env.responder = _failing
    return {}


def _setup_invalid_citation(env: Env, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    env.responder = _fabricated
    return {}


RESPONSE_PATHS = [
    pytest.param(_setup_answered, "answered", id="answered"),
    pytest.param(_setup_conflicting, "conflicting_evidence", id="conflicting_evidence"),
    pytest.param(_setup_no_cohort_match, "insufficient_evidence", id="no_cohort_match"),
    pytest.param(_setup_no_evidence, "insufficient_evidence", id="no_evidence"),
    pytest.param(_setup_corpus_failure, "insufficient_evidence", id="corpus_failure"),
    pytest.param(_setup_gemini_failure, "insufficient_evidence", id="gemini_failure"),
    pytest.param(_setup_invalid_citation, "insufficient_evidence", id="invalid_citation"),
]


@pytest.mark.parametrize(("setup", "expected_status"), RESPONSE_PATHS)
def test_public_response_shape_on_every_path(
    env: Env, monkeypatch: pytest.MonkeyPatch, setup: Callable[..., dict[str, Any]], expected_status: str
) -> None:
    overrides = setup(env, monkeypatch)

    response = env.raw(**overrides)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == expected_status
    _assert_public_shape(body)
    assert "corpus" not in body
    assert '"corpus"' not in response.text
    assert "chunk_text" not in response.text and "chunk text" not in response.text


@pytest.mark.parametrize(("setup", "expected_status"), RESPONSE_PATHS)
def test_internal_workflow_keeps_corpus_on_every_path(
    env: Env, monkeypatch: pytest.MonkeyPatch, setup: Callable[..., dict[str, Any]], expected_status: str
) -> None:
    overrides = setup(env, monkeypatch)
    batch = overrides.get("admission_batch", BATCH)

    internal = workflow.answer_student_question(batch, PROGRAMME, QUESTION, db_path=env.db_path)

    assert internal["status"] == expected_status
    assert "corpus" in internal  # unchanged internal contract for Streamlit


def test_retrieval_items_expose_exactly_the_public_metadata(env: Env) -> None:
    body = env.ask()

    results = body["retrieval"]["results"]
    assert results
    for item in results:
        assert set(item) == PUBLIC_RESULT_KEYS
        assert not ({"chunk_text", "chunk text", "verification_status", "applicable_batches"} & set(item))


# --------------------------------------------------------------------------- #
# D/E. Citations and validation are unchanged
# --------------------------------------------------------------------------- #


def test_valid_citation_and_supporting_text_are_returned(env: Env) -> None:
    body = env.ask()

    assert body["status"] == "answered"
    assert body["validation_issues"] == []
    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert citation == body["answer"]["citations"][0]
    assert citation["document_name"] == "R2024 Academic Regulations"
    assert citation["regulation_version"] == "R2024"
    assert citation["page_number"] == 1
    assert citation["relevant_supporting_text"] == CITED_QUOTE
    # The cited chunk is also identifiable among the retrieval metadata.
    assert citation["chunk_id"] in {item["chunk_id"] for item in body["retrieval"]["results"]}


def test_fabricated_citations_are_still_rejected(env: Env) -> None:
    env.responder = _fabricated

    body = env.ask()

    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert any("invented-chunk-99" in issue for issue in body["validation_issues"])
    assert "10 percent" not in body["answer"]["answer"]


def test_fabricated_quote_on_real_chunk_is_still_rejected(env: Env) -> None:
    def fabricated_quote(**kwargs: Any) -> GroundedAnswer:
        chunk = _chunk_with(list(kwargs["evidence_chunks"]), CITED_QUOTE)
        return GroundedAnswer(
            answer="Students need only 10 percent attendance.",
            status="answered",
            citations=[GroundedCitation(chunk_id=str(chunk["chunk_id"]), relevant_supporting_text="invented quote")],
        )

    env.responder = fabricated_quote

    body = env.ask()

    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert any("supporting text could not be matched" in issue for issue in body["validation_issues"])


# --------------------------------------------------------------------------- #
# F/G. Uncited text never leaves the backend; internal corpus is retained
# --------------------------------------------------------------------------- #


def test_uncited_regulation_text_never_appears_in_the_response(env: Env) -> None:
    response = env.raw()
    body = response.json()

    # The marker page really was part of the pipeline: retrieved and sent to Gemini ...
    evidence = env.generation_calls[0]["evidence_chunks"]
    marker_chunk = _chunk_with(list(evidence), "UNCITED-MARKER-7c2e")
    assert marker_chunk["chunk_id"] in {item["chunk_id"] for item in body["retrieval"]["results"]}
    # ... but it was not cited, so its text appears nowhere in the API response.
    assert body["status"] == "answered"
    assert "UNCITED-MARKER-7c2e" not in response.text
    assert "library fines" not in response.text


def test_internal_workflow_result_still_contains_the_full_corpus(env: Env) -> None:
    internal = workflow.answer_student_question(BATCH, PROGRAMME, QUESTION, db_path=env.db_path)

    corpus = internal["corpus"]
    assert corpus["status"] == "ok"
    assert [reg["document_name"] for reg in corpus["regulations"]] == ["R2024 Academic Regulations"]
    assert len(corpus["chunks"]) == 3
    assert any("UNCITED-MARKER-7c2e" in chunk["chunk_text"] for chunk in corpus["chunks"])
    assert all("chunk_text" in item for item in internal["retrieval"]["results"])
    assert set(internal) == PUBLIC_KEYS | {"corpus"}


# --------------------------------------------------------------------------- #
# H. Response size is bounded by top_k, not by the cohort corpus
# --------------------------------------------------------------------------- #


def _size_for_pages(tmp_path: Path, page_count: int, top_k: int = 5) -> tuple[int, int]:
    db_path = tmp_path / f"size_{page_count}.db"
    if not db_path.exists():
        init_database(db_path)
        filler = " ".join(f"clause{n} applies to attendance and assessment records" for n in range(15))
        _seed(
            db_path,
            name="Large Regulation",
            version="R1",
            pages=[f"Page {i}: {CITED_QUOTE}. {filler}" for i in range(1, page_count + 1)],
        )
    app.dependency_overrides[query_routes.get_db_path] = lambda: str(db_path)
    response = TestClient(app).post(
        ASK_URL, json={"question": QUESTION, "admission_batch": BATCH, "programme": PROGRAMME, "top_k": top_k}
    )
    assert response.status_code == 200
    internal = workflow.answer_student_question(BATCH, PROGRAMME, QUESTION, db_path=db_path, top_k=top_k)
    return len(response.content), len(json.dumps(internal["corpus"]))


def test_response_size_does_not_grow_with_the_cohort_corpus(env: Env, tmp_path: Path) -> None:
    small_response, small_corpus = _size_for_pages(tmp_path, 5)
    large_response, large_corpus = _size_for_pages(tmp_path, 200)

    # The internal corpus grows roughly linearly with the regulation ...
    assert large_corpus > 20 * small_corpus
    assert large_corpus > 200_000
    # ... while the public response stays bounded by top_k.
    assert large_response < small_response * 1.2
    assert large_response < 5_000


def test_response_size_is_bounded_at_maximum_top_k(env: Env, tmp_path: Path) -> None:
    response_size, corpus_size = _size_for_pages(tmp_path, 200, top_k=20)

    assert corpus_size > 200_000
    assert response_size < 10_000


# --------------------------------------------------------------------------- #
# I. OpenAPI documentation
# --------------------------------------------------------------------------- #


def test_openapi_does_not_document_corpus_or_chunk_text(env: Env) -> None:
    schemas = env.client.get("/openapi.json").json()["components"]["schemas"]

    assert set(schemas["GroundedAnswerResponse"]["properties"]) == PUBLIC_KEYS
    assert set(schemas["RetrievalResponse"]["properties"]) == PUBLIC_RETRIEVAL_KEYS
    assert set(schemas["RetrievalResultItem"]["properties"]) == PUBLIC_RESULT_KEYS
    for name in ("GroundedAnswerResponse", "RetrievalResponse", "RetrievalResultItem"):
        documented_fields = json.dumps(schemas[name]["properties"])
        assert "corpus" not in documented_fields
        assert "chunk_text" not in documented_fields
        assert "chunk text" not in documented_fields
    ask = env.client.get("/openapi.json").json()["paths"][ASK_URL]["post"]
    assert "corpus and raw chunk text are not included" in ask["responses"]["200"]["description"]


# --------------------------------------------------------------------------- #
# J. API consumers still get everything they need
# --------------------------------------------------------------------------- #


def test_consumers_receive_all_citation_and_retrieval_metadata(env: Env) -> None:
    body = env.ask()

    retrieval = body["retrieval"]
    assert retrieval["status"] == "ok"
    assert retrieval["message"]
    for item in retrieval["results"]:
        assert isinstance(item["chunk_id"], str) and item["chunk_id"]
        assert isinstance(item["regulation_id"], int)
        assert item["document_name"] == "R2024 Academic Regulations"
        assert item["regulation_version"] == "R2024"
        assert isinstance(item["page_number"], int)
        assert item["admission_batch"] == BATCH
        assert item["programme"] == PROGRAMME
        assert isinstance(item["retrieval_score"], float)
    assert body["answer"]["answer"]
    assert body["answer"]["status"] == "answered"


def test_consumers_can_still_show_multiple_regulation_versions(env: Env) -> None:
    """Metadata needed for a conflict/version panel (as Streamlit shows) is still returned."""
    _seed(
        env.db_path,
        name="R2025 Academic Regulations",
        version="R2025",
        pages=[f"Section 4.2 Attendance (revised). Every student must maintain a {CITED_QUOTE}."],
    )
    env.responder = _conflicting

    body = env.ask()

    versions = {(item["document_name"], item["regulation_version"]) for item in body["retrieval"]["results"]}
    assert versions == {("R2024 Academic Regulations", "R2024"), ("R2025 Academic Regulations", "R2025")}
    assert body["status"] == "conflicting_evidence"


def test_insufficient_evidence_still_explains_why(env: Env) -> None:
    body = env.ask(admission_batch="2019")

    assert body["answer"]["limitations"] == (
        "No approved regulations applicable to the supplied admission batch and programme were found."
    )
    assert body["retrieval"]["status"] == "no_evidence"
    assert body["retrieval"]["message"]
