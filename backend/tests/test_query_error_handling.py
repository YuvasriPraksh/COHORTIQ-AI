"""Error handling for the student question endpoint ``POST /api/v1/query/ask``.

Contract:
- Expected application outcomes (answered, insufficient_evidence,
  conflicting_evidence, citation-validation downgrades) return HTTP 200.
- Blank fields return 400; omitted fields return FastAPI's 422.
- Unexpected server exceptions return a generic HTTP 500 whose body never
  contains exception text, file paths, secrets or tracebacks. The original
  exception and traceback are logged server-side.

Gemini is always replaced by a test double; every test uses an isolated
temporary SQLite database.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app import workflow
from app.config import Settings
from app.database import init_database, insert_document_pages, insert_regulation
from app.models import GroundedAnswer, GroundedCitation
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.main import app
from backend.app.services import query_service

ASK_URL = "/api/v1/query/ask"
QUERY_LOGGER = "backend.app.api.v1.query"

BATCH = "2024"
PROGRAMME = "BSc CS"
PAGE_TEXT = "Students must maintain at least 75 percent attendance in each course to be eligible."
QUOTE = "at least 75 percent attendance"

SECRET_MARKER = "sk-PLANTED-SECRET-do-not-leak-1234"
PRIVATE_PATH = r"C:\srv\cohortiq\private\cohortiq.db"
PLANTED_EXCEPTION_TEXT = f"GEMINI_API_KEY={SECRET_MARKER} database={PRIVATE_PATH}"
PRIVATE_QUESTION_MARKER = "STUDENT-PRIVATE-QUESTION-MARKER"


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    db_path = tmp_path / "query_errors.db"
    init_database(db_path)
    _seed_approved_regulation(db_path)

    app.dependency_overrides[query_routes.get_db_path] = lambda: str(db_path)
    app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(db_path)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(query_routes.get_db_path, None)
        app.dependency_overrides.pop(regulation_routes.get_db_path, None)


def _seed_approved_regulation(db_path: Path) -> int:
    regulation_id = insert_regulation(
        {
            "document_name": "Attendance Rules",
            "regulation_version": "R2024",
            "effective_date": "2024-08-01",
            "applicable_batches": [BATCH],
            "applicable_programmes": [PROGRAMME],
            "upload_date": "2024-07-01",
            "total_pages": 1,
            "processing_status": "extracted",
            "verification_status": "approved",
        },
        db_path=db_path,
    )
    insert_document_pages(
        regulation_id,
        [{"page_number": 1, "extracted_text": PAGE_TEXT, "extraction_status": "success"}],
        db_path=db_path,
    )
    return regulation_id


def _ask(client: TestClient, **overrides: Any):
    payload = {
        "question": "What is the attendance requirement?",
        "admission_batch": BATCH,
        "programme": PROGRAMME,
        **overrides,
    }
    return client.post(ASK_URL, json=payload)


def _answer_citing_first_chunk(**kwargs: Any) -> GroundedAnswer:
    chunk = dict((kwargs.get("evidence_chunks") or [])[0])
    return GroundedAnswer(
        answer="Students must maintain at least 75 percent attendance.",
        status="answered",
        citations=[
            GroundedCitation(
                document_name=chunk.get("document_name"),
                regulation_version=chunk.get("regulation_version"),
                page_number=chunk.get("page_number"),
                chunk_id=str(chunk.get("chunk_id")),
                relevant_supporting_text=QUOTE,
            )
        ],
    )


def _assert_generic_500(response: Any) -> None:
    assert response.status_code == 500
    assert response.json() == {"detail": query_routes.QUERY_INTERNAL_ERROR_DETAIL}
    body = response.text
    for forbidden in (
        SECRET_MARKER,
        "GEMINI_API_KEY",
        PRIVATE_PATH,
        "private",
        "cohortiq.db",
        "Traceback",
        'File "',
        ".py",
        "Error",  # exception class names such as RuntimeError / ValidationError
        "Failed to answer student question",
    ):
        assert forbidden not in body, f"Response leaked {forbidden!r}: {body}"


# --------------------------------------------------------------------------- #
# Expected outcomes remain HTTP 200
# --------------------------------------------------------------------------- #


def test_grounded_answer_still_returned(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.workflow.generate_grounded_answer", _answer_citing_first_chunk)

    response = _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["validation_issues"] == []
    assert len(body["citations"]) == 1
    assert body["citations"][0]["document_name"] == "Attendance Rules"
    assert body["citations"][0]["relevant_supporting_text"] == QUOTE


def test_insufficient_evidence_for_other_cohort_still_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr("app.workflow.generate_grounded_answer", lambda **kw: calls.append(kw))

    response = _ask(client, admission_batch="2019")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert calls == [], "Cohort filtering must stop generation for a non-applicable cohort."


def test_conflicting_evidence_outcome_still_returns_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def conflicting(**kwargs: Any) -> GroundedAnswer:
        return _answer_citing_first_chunk(**kwargs).model_copy(update={"status": "conflicting_evidence"})

    monkeypatch.setattr("app.workflow.generate_grounded_answer", conflicting)

    response = _ask(client)

    assert response.status_code == 200
    assert response.json()["status"] == "conflicting_evidence"


def test_answer_generation_failure_handled_by_workflow_is_not_a_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workflow turns Gemini failures into insufficient evidence; that stays HTTP 200."""

    def failing_generation(**_kwargs: Any) -> GroundedAnswer:
        raise ConnectionError("simulated Gemini outage")

    monkeypatch.setattr("app.workflow.generate_grounded_answer", failing_generation)

    response = _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []


def test_fabricated_citation_is_downgraded_not_a_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fabricated(**_kwargs: Any) -> GroundedAnswer:
        return GroundedAnswer(
            answer="Only 10 percent attendance is needed.",
            status="answered",
            citations=[GroundedCitation(chunk_id="invented-chunk", relevant_supporting_text="10 percent")],
        )

    monkeypatch.setattr("app.workflow.generate_grounded_answer", fabricated)

    response = _ask(client)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert any("invented-chunk" in issue for issue in body["validation_issues"])


def test_blank_and_missing_fields_keep_their_client_error_codes(client: TestClient) -> None:
    blank = _ask(client, question="   ")
    assert blank.status_code == 400
    assert blank.json() == {"detail": "question, admission_batch, and programme are required."}

    missing = client.post(ASK_URL, json={"question": "Attendance?", "admission_batch": BATCH})
    assert missing.status_code == 422


# --------------------------------------------------------------------------- #
# Unexpected exceptions become a generic, non-leaking HTTP 500
# --------------------------------------------------------------------------- #


def _raise_planted(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError(PLANTED_EXCEPTION_TEXT)


@pytest.mark.parametrize(
    "target",
    [
        pytest.param("app.workflow.retrieve_relevant_chunks", id="retrieval_crash"),
        pytest.param("app.workflow.build_retrieval_corpus_for_cohort", id="corpus_crash"),
        pytest.param(
            "backend.app.services.query_service.answer_student_regulation_question",
            id="service_crash",
        ),
    ],
)
def test_unexpected_exception_returns_generic_500(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    target: str,
) -> None:
    monkeypatch.setattr(target, _raise_planted)

    with caplog.at_level(logging.ERROR, logger=QUERY_LOGGER):
        response = _ask(client, question=f"Attendance rules? {PRIVATE_QUESTION_MARKER}")

    _assert_generic_500(response)

    # The original exception and its traceback are logged server-side.
    records = [record for record in caplog.records if record.name == QUERY_LOGGER]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None
    assert isinstance(record.exc_info[1], RuntimeError)
    assert PLANTED_EXCEPTION_TEXT in caplog.text
    assert "Traceback" in caplog.text
    assert f"admission_batch='{BATCH}'" in record.getMessage()
    # Student-entered question text is not written to the logs.
    assert PRIVATE_QUESTION_MARKER not in caplog.text


def test_malformed_workflow_result_returns_generic_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A response-schema validation failure must not echo pydantic's error text."""
    monkeypatch.setattr(
        query_service,
        "answer_student_regulation_question",
        lambda **_kwargs: {"status": "answered", "answer": {"secret": PLANTED_EXCEPTION_TEXT}},
    )

    response = _ask(client)

    _assert_generic_500(response)


def test_generic_500_does_not_chain_original_exception(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with server exceptions surfaced to the test client, the route returns a clean 500."""
    monkeypatch.setattr("app.workflow.retrieve_relevant_chunks", _raise_planted)

    strict_client = TestClient(app, raise_server_exceptions=True)
    response = _ask(strict_client)

    _assert_generic_500(response)


def test_openapi_documents_query_error_responses(client: TestClient) -> None:
    responses = client.get("/openapi.json").json()["paths"][ASK_URL]["post"]["responses"]
    assert {"200", "400", "422", "500"} <= set(responses)


# --------------------------------------------------------------------------- #
# Internal failures handled inside the workflow: safe HTTP 200 bodies
# --------------------------------------------------------------------------- #
#
# These failures are expected application outcomes (insufficient evidence), so
# they stay HTTP 200. Their user-facing fields must carry safe messages only,
# while the technical details are logged server-side.

WORKFLOW_LOGGER = "app.workflow"
GEMINI_LOGGER = "app.gemini_service"


def _planted_text(tmp_path: Path) -> str:
    """Exception text containing a secret, a private path and the temp DB path."""
    return f"{PLANTED_EXCEPTION_TEXT} temp={tmp_path / 'query_errors.db'}"


def _all_strings(value: Any) -> Iterator[str]:
    """Yield every string (keys and values) in a decoded JSON structure."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)


def _assert_safe_200(response: Any, tmp_path: Path) -> dict[str, Any]:
    """HTTP 200 whose decoded body contains no internal details anywhere."""
    assert response.status_code == 200, response.text
    body = response.json()
    forbidden = (
        SECRET_MARKER,
        PRIVATE_PATH,
        str(tmp_path),
        "GEMINI_API_KEY",
        ".env",
        "Traceback",
        'File "',
        "OperationalError",
        "RuntimeError",
        "ValueError",
        PRIVATE_QUESTION_MARKER,
    )
    for text in _all_strings(body):
        for marker in forbidden:
            assert marker not in text, f"Response leaked {marker!r} in {text!r}"
    # Raw-text check as well (catches anything outside decoded strings).
    assert SECRET_MARKER not in response.text
    return body


def _ask_private(client: TestClient, **overrides: Any):
    """Ask with a planted marker in the question to verify it is never logged."""
    return _ask(client, question=f"What is the attendance requirement? {PRIVATE_QUESTION_MARKER}", **overrides)


def _assert_logged(caplog: pytest.LogCaptureFixture, logger_name: str, planted: str, *, traceback: bool = True) -> None:
    records = [record for record in caplog.records if record.name == logger_name]
    assert records, f"Nothing was logged by {logger_name}."
    assert planted in caplog.text, "Technical details must be retained in server logs."
    if traceback:
        assert any(record.exc_info for record in records), "Traceback must be logged."
    assert PRIVATE_QUESTION_MARKER not in caplog.text, "Student question text must not be logged."


def _isolated_gemini(monkeypatch: pytest.MonkeyPatch, *, api_key: str | None, generate: Any) -> None:
    """Run the real Gemini service against a fake google-genai client (no network)."""
    settings = Settings(gemini_api_key=api_key, gemini_model="fake-model")
    monkeypatch.setattr("app.gemini_service.get_settings", lambda: settings)
    fake_client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    monkeypatch.setattr("app.gemini_service.genai", SimpleNamespace(Client=lambda **_kw: fake_client))


def test_regulation_lookup_failure_returns_safe_messages(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    planted = _planted_text(tmp_path)

    def failing_lookup(*_args: Any, **_kwargs: Any) -> Any:
        raise sqlite3.OperationalError(planted)

    monkeypatch.setattr("app.workflow.get_applicable_regulations", failing_lookup)

    with caplog.at_level(logging.ERROR, logger=WORKFLOW_LOGGER):
        body = _assert_safe_200(_ask_private(client), tmp_path)

    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert body["answer"]["limitations"] == workflow.SAFE_REGULATION_LOOKUP_FAILURE
    assert body["retrieval"]["message"] == workflow.SAFE_REGULATION_LOOKUP_FAILURE
    assert body["corpus"]["message"] == workflow.SAFE_REGULATION_LOOKUP_FAILURE
    _assert_logged(caplog, WORKFLOW_LOGGER, planted)


def test_page_loading_failure_is_safe_and_other_regulations_still_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    db_path = tmp_path / "query_errors.db"
    healthy_id = insert_regulation(
        {
            "document_name": "Attendance Rules Supplement",
            "regulation_version": "R2024-S1",
            "effective_date": "2024-08-01",
            "applicable_batches": [BATCH],
            "applicable_programmes": [PROGRAMME],
            "upload_date": "2024-07-01",
            "total_pages": 1,
            "processing_status": "extracted",
            "verification_status": "approved",
        },
        db_path=db_path,
    )
    insert_document_pages(
        healthy_id,
        [{"page_number": 1, "extracted_text": PAGE_TEXT, "extraction_status": "success"}],
        db_path=db_path,
    )
    planted = _planted_text(tmp_path)
    real_get_pages = workflow.get_document_pages

    def failing_for_first_regulation(regulation_id: int, db_path: Any = None) -> Any:
        if regulation_id != healthy_id:
            raise sqlite3.OperationalError(planted)
        return real_get_pages(regulation_id, db_path=db_path)

    monkeypatch.setattr("app.workflow.get_document_pages", failing_for_first_regulation)
    monkeypatch.setattr("app.workflow.generate_grounded_answer", _answer_citing_first_chunk)

    with caplog.at_level(logging.ERROR, logger=WORKFLOW_LOGGER):
        body = _assert_safe_200(_ask_private(client), tmp_path)

    # The healthy regulation still supports a grounded, validated answer.
    assert body["status"] == "answered"
    assert {c["document_name"] for c in body["citations"]} == {"Attendance Rules Supplement"}

    failed = [r for r in body["corpus"]["regulations"] if r["id"] != healthy_id]
    assert len(failed) == 1
    assert failed[0]["page_load_error"] == workflow.SAFE_PAGE_LOAD_FAILURE
    assert failed[0]["pages_loaded"] == 0
    _assert_logged(caplog, WORKFLOW_LOGGER, planted)


def test_chunk_creation_failure_is_logged_and_not_exposed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    planted = _planted_text(tmp_path)

    def failing_chunker(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(planted)

    monkeypatch.setattr("app.workflow.create_chunks", failing_chunker)

    with caplog.at_level(logging.ERROR, logger=WORKFLOW_LOGGER):
        body = _assert_safe_200(_ask_private(client), tmp_path)

    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    _assert_logged(caplog, WORKFLOW_LOGGER, planted)


def test_gemini_configuration_failure_returns_safe_limitation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """Missing API key: the real service raises; the client sees no configuration details."""

    def must_not_be_called(**_kwargs: Any) -> Any:
        raise AssertionError("Gemini must not be called without an API key.")

    _isolated_gemini(monkeypatch, api_key=None, generate=must_not_be_called)

    with caplog.at_level(logging.ERROR, logger=WORKFLOW_LOGGER):
        body = _assert_safe_200(_ask_private(client), tmp_path)

    assert body["status"] == "insufficient_evidence"
    assert body["answer"]["limitations"] == workflow.SAFE_GENERATION_NOT_CONFIGURED
    # Keeps the wording the Streamlit assistant uses to show its configuration hint.
    assert "not configured" in body["answer"]["limitations"].lower()
    _assert_logged(caplog, WORKFLOW_LOGGER, "GEMINI_API_KEY is not configured")


def test_gemini_generation_failure_returns_safe_limitation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """An exception escaping the generation layer is logged, not returned."""
    planted = _planted_text(tmp_path)

    def failing_generation(**_kwargs: Any) -> Any:
        raise RuntimeError(planted)

    monkeypatch.setattr("app.workflow.generate_grounded_answer", failing_generation)

    with caplog.at_level(logging.ERROR, logger=WORKFLOW_LOGGER):
        body = _assert_safe_200(_ask_private(client), tmp_path)

    assert body["status"] == "insufficient_evidence"
    assert body["answer"]["limitations"] == workflow.SAFE_GENERATION_FAILURE
    limitation = body["answer"]["limitations"].lower()
    assert "gemini" in limitation and "failed" in limitation  # Streamlit hint wording
    _assert_logged(caplog, WORKFLOW_LOGGER, planted)


def test_gemini_client_failure_inside_service_is_logged_not_returned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    planted = _planted_text(tmp_path)

    def failing_model_call(**_kwargs: Any) -> Any:
        raise RuntimeError(planted)

    _isolated_gemini(monkeypatch, api_key="test-dummy-key", generate=failing_model_call)

    with caplog.at_level(logging.WARNING, logger=GEMINI_LOGGER):
        body = _assert_safe_200(_ask_private(client), tmp_path)

    assert body["status"] == "insufficient_evidence"
    assert body["answer"]["limitations"] == "Unexpected Gemini service error."
    _assert_logged(caplog, GEMINI_LOGGER, planted)


def test_invalid_model_output_details_are_logged_not_returned(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """Validation errors can echo model output; only a generic limitation is returned."""
    planted = _planted_text(tmp_path)

    def valid_json(**_kwargs: Any) -> Any:
        return SimpleNamespace(text='{"answer": "x", "status": "answered", "citations": []}')

    def failing_normalization(*_args: Any, **_kwargs: Any) -> Any:
        raise ValueError(planted)

    _isolated_gemini(monkeypatch, api_key="test-dummy-key", generate=valid_json)
    monkeypatch.setattr("app.gemini_service._normalize_model_response", failing_normalization)

    with caplog.at_level(logging.WARNING, logger=GEMINI_LOGGER):
        body = _assert_safe_200(_ask_private(client), tmp_path)

    assert body["status"] == "insufficient_evidence"
    assert body["answer"]["limitations"] == "The model response was invalid or incomplete."
    _assert_logged(caplog, GEMINI_LOGGER, planted, traceback=False)


def test_citation_validation_failure_returns_safe_issue_and_limitation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    planted = _planted_text(tmp_path)

    def failing_validator(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError(planted)

    monkeypatch.setattr("app.workflow.generate_grounded_answer", _answer_citing_first_chunk)
    monkeypatch.setattr("app.workflow.validate_grounded_answer", failing_validator)

    with caplog.at_level(logging.ERROR, logger=WORKFLOW_LOGGER):
        body = _assert_safe_200(_ask_private(client), tmp_path)

    # An unvalidated answer is never shown.
    assert body["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert body["answer"]["limitations"] == workflow.SAFE_CITATION_VALIDATION_FAILURE
    assert body["validation_issues"] == [workflow.SAFE_CITATION_VALIDATION_ISSUE]
    _assert_logged(caplog, WORKFLOW_LOGGER, planted)


def test_normal_no_evidence_message_is_unchanged(client: TestClient) -> None:
    body = _ask(client, admission_batch="2019").json()

    assert body["answer"]["limitations"] == (
        "No approved regulations applicable to the supplied admission batch and programme were found."
    )
