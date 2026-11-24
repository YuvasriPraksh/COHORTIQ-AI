"""End-to-end integration tests for the CohortIQ AI backend workflow.

These tests drive the real FastAPI application through its public HTTP API and
exercise the complete pipeline with no business logic mocked:

    PDF upload -> extraction -> SQLite storage (pending) -> explicit approval
    -> cohort applicability filtering -> chunking -> BM25 retrieval
    -> Gemini prompt construction / response parsing -> citation validation

Only the outermost external dependency is replaced: the ``google-genai`` client
used by ``app.gemini_service``. The fake client records every prompt and returns
scripted model output, so no network request or paid API call is ever made.

Isolation guarantees:
- Every test uses its own temporary SQLite database (both routers'
  ``get_db_path`` dependencies are overridden).
- The database layer's default-path fallback is redirected to a temporary
  "must not be used" path, and teardown asserts it was never created.
- Teardown asserts the real project database file was not modified.
- Gemini settings use a dummy API key, so the real ``.env`` key is never read
  by the answer-generation path.
- Regulation PDFs are generated on the fly with PyMuPDF.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import quote

import fitz
import pytest
from fastapi.testclient import TestClient

from app import config as app_config
from app import gemini_service
from app.config import Settings
from app.database import init_database
from app.models import GroundedAnswer, GroundedCitation
from backend.app.api.v1 import query as query_routes
from backend.app.api.v1 import regulations as regulation_routes
from backend.app.main import app
from backend.app.services import regulation_service

API = "/api/v1"

COHORT_BATCH = "2024"
COHORT_PROGRAMME = "B.Tech CSE"
OTHER_BATCH = "2019"
OTHER_PROGRAMME = "MBA"

FAKE_API_KEY = "test-e2e-dummy-key"
FAKE_MODEL = "fake-gemini-model-for-tests"

ATTENDANCE_QUESTION = "What is the minimum attendance required to sit the end semester examination?"

# Each inner list is one PDF page; each string is one rendered text line.
# Sentences are kept on a single line so quotes can be matched exactly.
APPROVED_PAGES: list[list[str]] = [
    [
        "Section 4.2 Attendance Requirements",
        "Every student must maintain a minimum of 75 percent attendance in each course.",
        "Students below this attendance are not eligible for the end semester examination.",
    ],
    [
        "Section 7.1 Grading and Passing",
        "A student must secure a minimum grade point of 5.0 to pass a course.",
    ],
]
APPROVED_ATTENDANCE_QUOTE = "minimum of 75 percent attendance in each course"

PENDING_PAGES: list[list[str]] = [
    [
        "Draft Section 4.2 Attendance",
        "Draft rule: students need 60 percent attendance to sit the end semester examination.",
    ]
]
PENDING_UNIQUE_TEXT = "60 percent attendance"

REJECTED_PAGES: list[list[str]] = [
    [
        "Withdrawn Section 4.2 Attendance",
        "Withdrawn rule: students need 50 percent attendance to sit the end semester examination.",
    ]
]
REJECTED_UNIQUE_TEXT = "50 percent attendance"

FABRICATED_QUOTE = "students need only 10 percent attendance to pass"


# --------------------------------------------------------------------------- #
# Fake Gemini client
# --------------------------------------------------------------------------- #

Responder = Callable[[str, Sequence[Mapping[str, Any]]], str]
AnswerOverride = Callable[..., GroundedAnswer]


def _insufficient_json(_prompt: str, _evidence: Sequence[Mapping[str, Any]]) -> str:
    """Default scripted model output: a conservative insufficient-evidence answer."""
    return json.dumps(
        {
            "answer": "The supplied evidence does not answer this question.",
            "status": "insufficient_evidence",
            "citations": [],
            "limitations": "Scripted default response.",
        }
    )


@dataclass
class FakeGemini:
    """Stand-in for ``google.genai``: records calls and never touches the network."""

    responder: Responder = _insufficient_json
    answer_override: AnswerOverride | None = None
    client_api_keys: list[str | None] = field(default_factory=list)
    model_calls: list[dict[str, Any]] = field(default_factory=list)
    generation_calls: list[dict[str, Any]] = field(default_factory=list)
    _current_evidence: list[dict[str, Any]] = field(default_factory=list)

    # -- google.genai surface ------------------------------------------------
    def Client(self, *args: Any, api_key: str | None = None, **kwargs: Any) -> Any:  # noqa: N802
        """Mimic ``genai.Client(api_key=...)``."""
        self.client_api_keys.append(api_key)
        models = SimpleNamespace(generate_content=self._generate_content)
        return SimpleNamespace(models=models)

    def _generate_content(self, *, model: str, contents: str) -> Any:
        self.model_calls.append({"model": model, "prompt": contents})
        text = self.responder(contents, self._current_evidence)
        return SimpleNamespace(text=text)

    # -- helpers for assertions ---------------------------------------------
    @property
    def last_prompt(self) -> str:
        assert self.model_calls, "Gemini was never called."
        return self.model_calls[-1]["prompt"]

    @property
    def last_evidence(self) -> list[dict[str, Any]]:
        assert self.generation_calls, "Answer generation was never invoked."
        return self.generation_calls[-1]["evidence_chunks"]


@dataclass
class E2EEnv:
    """Handles for one isolated end-to-end test environment."""

    client: TestClient
    db_path: Path
    tmp_path: Path
    gemini: FakeGemini
    ingested_temp_paths: list[Path]


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[E2EEnv]:
    """Provide a fully isolated API client, temp database and fake Gemini."""
    real_db_path = Path(app_config.get_settings().database_path).resolve()
    real_db_stat_before = _file_signature(real_db_path)

    db_path = tmp_path / "e2e_cohortiq.db"
    init_database(db_path)

    # Any code path that falls back to the configured default database (or the
    # real Gemini key) is redirected to throwaway test values.
    unexpected_default_db = tmp_path / "unexpected_default_database.db"
    isolated_settings = Settings(
        gemini_api_key=FAKE_API_KEY,
        gemini_model=FAKE_MODEL,
        database_path=unexpected_default_db,
        upload_dir=tmp_path / "uploads",
        extracted_dir=tmp_path / "extracted",
    )
    monkeypatch.setattr("app.database.get_settings", lambda: isolated_settings)
    monkeypatch.setattr("app.gemini_service.get_settings", lambda: isolated_settings)

    # Replace only the external google-genai client.
    fake = FakeGemini()
    monkeypatch.setattr("app.gemini_service.genai", SimpleNamespace(Client=fake.Client))

    # Spy on the workflow -> Gemini boundary to capture the exact evidence sent
    # to answer generation, then delegate to the real Gemini service.
    real_generate = gemini_service.generate_grounded_answer

    def spying_generate(**kwargs: Any) -> GroundedAnswer:
        evidence = [dict(item) for item in (kwargs.get("evidence_chunks") or [])]
        fake.generation_calls.append({**kwargs, "evidence_chunks": evidence})
        fake._current_evidence = evidence
        if fake.answer_override is not None:
            return fake.answer_override(**kwargs)
        return real_generate(**kwargs)

    monkeypatch.setattr("app.workflow.generate_grounded_answer", spying_generate)

    # Record temporary upload paths so cleanup can be verified.
    ingested_temp_paths: list[Path] = []
    real_ingest = regulation_service.ingest_regulation

    def spying_ingest(pdf_path: Any, metadata: Any, db_path: Any = None) -> dict[str, Any]:
        ingested_temp_paths.append(Path(pdf_path))
        return real_ingest(pdf_path=pdf_path, metadata=metadata, db_path=db_path)

    monkeypatch.setattr(regulation_service, "ingest_regulation", spying_ingest)

    app.dependency_overrides[regulation_routes.get_db_path] = lambda: str(db_path)
    app.dependency_overrides[query_routes.get_db_path] = lambda: str(db_path)
    try:
        yield E2EEnv(
            client=TestClient(app),
            db_path=db_path,
            tmp_path=tmp_path,
            gemini=fake,
            ingested_temp_paths=ingested_temp_paths,
        )
    finally:
        app.dependency_overrides.pop(regulation_routes.get_db_path, None)
        app.dependency_overrides.pop(query_routes.get_db_path, None)

    assert not unexpected_default_db.exists(), "A code path used the default database path."
    assert _file_signature(real_db_path) == real_db_stat_before, "The real project database changed."
    assert all(key == FAKE_API_KEY for key in fake.client_api_keys), "A non-test API key was used."


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _file_signature(path: Path) -> tuple[int, int] | None:
    """Return (size, mtime_ns) for a file, or None when it does not exist."""
    if not path.exists():
        return None
    stat = path.stat()
    return (stat.st_size, stat.st_mtime_ns)


def _create_regulation_pdf(directory: Path, filename: str, pages: list[list[str]]) -> Path:
    """Generate a real multi-page regulation PDF with the given text lines."""
    pdf_path = directory / filename
    document = fitz.open()
    try:
        for lines in pages:
            page = document.new_page()
            for line_index, line in enumerate(lines):
                page.insert_text((56, 72 + line_index * 18), line, fontsize=10)
        document.save(pdf_path)
    finally:
        document.close()
    return pdf_path


def _ingest(
    env: E2EEnv,
    *,
    filename: str,
    pages: list[list[str]],
    document_name: str,
    regulation_version: str,
    batches: list[str] | None = None,
    programmes: list[str] | None = None,
) -> dict[str, Any]:
    """Upload a generated PDF through the ingestion API and return the JSON body."""
    pdf_path = _create_regulation_pdf(env.tmp_path, filename, pages)
    with pdf_path.open("rb") as pdf_file:
        response = env.client.post(
            f"{API}/regulations/ingest",
            data={
                "document_name": document_name,
                "regulation_version": regulation_version,
                "effective_date": "2024-07-01",
                "applicable_batches": batches or [COHORT_BATCH],
                "applicable_programmes": programmes or [COHORT_PROGRAMME],
            },
            files={"file": (filename, pdf_file, "application/pdf")},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ingested", body
    return body


def _ingest_approved_regulation(env: E2EEnv) -> int:
    regulation_id = _ingest(
        env,
        filename="r2024_regulations.pdf",
        pages=APPROVED_PAGES,
        document_name="R2024 B.Tech Regulations",
        regulation_version="R2024",
    )["regulation_id"]
    _set_verification(env, regulation_id, "approved")
    return regulation_id


def _set_verification(env: E2EEnv, regulation_id: int, status: str) -> dict[str, Any]:
    response = env.client.patch(
        f"{API}/regulations/{regulation_id}/verification",
        json={"verification_status": status},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "updated"
    assert body["verification_status"] == status
    return body


def _cohort_regulation_ids(env: E2EEnv, batch: str, programme: str) -> list[int]:
    response = env.client.get(f"{API}/cohorts/{quote(batch, safe='')}/{quote(programme, safe='')}/regulations")
    assert response.status_code == 200, response.text
    return [regulation["id"] for regulation in response.json()["regulations"]]


def _ask(
    env: E2EEnv,
    question: str = ATTENDANCE_QUESTION,
    batch: str = COHORT_BATCH,
    programme: str = COHORT_PROGRAMME,
) -> dict[str, Any]:
    response = env.client.post(
        f"{API}/query/ask",
        json={"question": question, "admission_batch": batch, "programme": programme},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _chunk_containing(evidence: Sequence[Mapping[str, Any]], text: str) -> Mapping[str, Any]:
    for chunk in evidence:
        if text in str(chunk.get("chunk_text", "")):
            return chunk
    raise AssertionError(f"No evidence chunk contains {text!r}.")


def _answered_citing(quote_text: str) -> Responder:
    """Scripted model output that answers and cites the chunk containing quote_text."""

    def responder(_prompt: str, evidence: Sequence[Mapping[str, Any]]) -> str:
        chunk = _chunk_containing(evidence, quote_text)
        return json.dumps(
            {
                "answer": "Students must maintain a minimum of 75 percent attendance in each course.",
                "status": "answered",
                "citations": [
                    {
                        "document_name": chunk.get("document_name"),
                        "regulation_version": chunk.get("regulation_version"),
                        "page_number": chunk.get("page_number"),
                        "chunk_id": chunk.get("chunk_id"),
                        "relevant_supporting_text": quote_text,
                    }
                ],
                "limitations": None,
            }
        )

    return responder


def _assert_safe_insufficient(body: dict[str, Any]) -> None:
    """A safe response never claims an answer and never carries citations."""
    assert body["status"] == "insufficient_evidence"
    assert body["answer"]["status"] == "insufficient_evidence"
    assert body["citations"] == []
    assert body["answer"]["citations"] == []
    assert body["answer"]["answer"].strip()
    assert body["answer"]["limitations"]


# --------------------------------------------------------------------------- #
# 1-3. Ingestion, extraction and initial pending status
# --------------------------------------------------------------------------- #


def test_ingestion_extracts_pages_and_stores_regulation_as_pending(env: E2EEnv) -> None:
    body = _ingest(
        env,
        filename="r2024_regulations.pdf",
        pages=APPROVED_PAGES,
        document_name="R2024 B.Tech Regulations",
        regulation_version="R2024",
    )

    regulation_id = body["regulation_id"]
    assert isinstance(regulation_id, int)
    assert body["verification_status"] == "pending"

    summary = body["extraction_summary"]
    assert summary["total_pages"] == 2
    assert summary["successful_pages"] == 2
    assert summary["pages_needing_attention"] == 0
    assert [page["page_number"] for page in summary["pages"]] == [1, 2]

    detail = env.client.get(f"{API}/regulations/{regulation_id}")
    assert detail.status_code == 200
    regulation = detail.json()["regulation"]
    assert regulation["verification_status"] == "pending"
    assert regulation["processing_status"] == "extracted"
    assert regulation["document_name"] == "R2024 B.Tech Regulations"
    assert regulation["regulation_version"] == "R2024"
    assert regulation["total_pages"] == 2
    assert regulation["applicable_batches"] == [COHORT_BATCH]
    assert regulation["applicable_programmes"] == [COHORT_PROGRAMME]

    pages_response = env.client.get(f"{API}/regulations/{regulation_id}/pages")
    assert pages_response.status_code == 200
    pages = pages_response.json()["pages"]
    assert [page["page_number"] for page in pages] == [1, 2]
    assert all(page["extraction_status"] == "success" for page in pages)
    assert APPROVED_ATTENDANCE_QUOTE in pages[0]["extracted_text"]
    assert "minimum grade point of 5.0" in pages[1]["extracted_text"]

    # The uploaded file is processed from a temporary path that is removed afterwards.
    assert len(env.ingested_temp_paths) == 1
    assert not env.ingested_temp_paths[0].exists()


def test_pending_regulation_is_invisible_to_students_until_approved(env: E2EEnv) -> None:
    regulation_id = _ingest(
        env,
        filename="r2024_regulations.pdf",
        pages=APPROVED_PAGES,
        document_name="R2024 B.Tech Regulations",
        regulation_version="R2024",
    )["regulation_id"]

    assert _cohort_regulation_ids(env, COHORT_BATCH, COHORT_PROGRAMME) == []

    body = _ask(env)
    _assert_safe_insufficient(body)
    assert env.gemini.model_calls == [], "Gemini must not be called without approved evidence."

    # Still pending after the student query: nothing auto-approves.
    regulation = env.client.get(f"{API}/regulations/{regulation_id}").json()["regulation"]
    assert regulation["verification_status"] == "pending"


def test_corrupted_pdf_upload_is_not_stored(env: E2EEnv) -> None:
    response = env.client.post(
        f"{API}/regulations/ingest",
        data={
            "document_name": "Broken Upload",
            "regulation_version": "R2024",
            "effective_date": "2024-07-01",
            "applicable_batches": [COHORT_BATCH],
            "applicable_programmes": [COHORT_PROGRAMME],
        },
        files={"file": ("broken.pdf", b"%PDF-1.7 this is not a valid pdf body", "application/pdf")},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": regulation_routes.INVALID_PDF_DETAIL}

    assert env.client.get(f"{API}/regulations").json()["regulations"] == []
    assert not env.ingested_temp_paths[0].exists()


# --------------------------------------------------------------------------- #
# 4-6. Explicit approval and cohort applicability
# --------------------------------------------------------------------------- #


def test_approval_publishes_regulation_only_to_its_cohort(env: E2EEnv) -> None:
    regulation_id = _ingest(
        env,
        filename="r2024_regulations.pdf",
        pages=APPROVED_PAGES,
        document_name="R2024 B.Tech Regulations",
        regulation_version="R2024",
    )["regulation_id"]

    _set_verification(env, regulation_id, "approved")

    regulation = env.client.get(f"{API}/regulations/{regulation_id}").json()["regulation"]
    assert regulation["verification_status"] == "approved"

    assert _cohort_regulation_ids(env, COHORT_BATCH, COHORT_PROGRAMME) == [regulation_id]

    # Batch alone or programme alone is not enough: both must match.
    assert _cohort_regulation_ids(env, OTHER_BATCH, COHORT_PROGRAMME) == []
    assert _cohort_regulation_ids(env, COHORT_BATCH, OTHER_PROGRAMME) == []
    assert _cohort_regulation_ids(env, OTHER_BATCH, OTHER_PROGRAMME) == []


def test_other_cohort_cannot_obtain_answers_from_approved_regulation(env: E2EEnv) -> None:
    _ingest_approved_regulation(env)
    env.gemini.responder = _answered_citing(APPROVED_ATTENDANCE_QUOTE)

    for batch, programme in (
        (OTHER_BATCH, COHORT_PROGRAMME),
        (COHORT_BATCH, OTHER_PROGRAMME),
    ):
        body = _ask(env, batch=batch, programme=programme)
        _assert_safe_insufficient(body)
        assert body["retrieval"]["results"] == []

    assert env.gemini.model_calls == [], "Gemini must not be called for a non-applicable cohort."


# --------------------------------------------------------------------------- #
# 7-10. Student question answered from approved evidence
# --------------------------------------------------------------------------- #


def test_student_question_is_answered_from_approved_evidence_with_citations(env: E2EEnv) -> None:
    regulation_id = _ingest_approved_regulation(env)
    env.gemini.responder = _answered_citing(APPROVED_ATTENDANCE_QUOTE)

    body = _ask(env)

    # Answer and validated citation are returned.
    assert body["status"] == "answered"
    assert body["answer"]["status"] == "answered"
    assert "75 percent attendance" in body["answer"]["answer"]
    assert body["validation_issues"] == []
    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert citation == body["answer"]["citations"][0]
    assert citation["document_name"] == "R2024 B.Tech Regulations"
    assert citation["regulation_version"] == "R2024"
    assert citation["page_number"] == 1
    assert citation["chunk_id"].startswith(f"{regulation_id}-p1-")
    assert citation["relevant_supporting_text"] == APPROVED_ATTENDANCE_QUOTE

    # Retrieval was cohort-scoped and ranked the attendance page first.
    retrieval = body["retrieval"]
    assert retrieval["status"] == "ok"
    assert retrieval["results"][0]["page_number"] == 1
    assert all(result["regulation_id"] == regulation_id for result in retrieval["results"])
    assert all(result["admission_batch"] == COHORT_BATCH for result in retrieval["results"])
    assert all(result["programme"] == COHORT_PROGRAMME for result in retrieval["results"])

    # Exactly one generation call, with the approved evidence and cohort context.
    assert len(env.gemini.generation_calls) == 1
    call = env.gemini.generation_calls[0]
    assert call["question"] == ATTENDANCE_QUESTION
    assert call["admission_batch"] == COHORT_BATCH
    assert call["programme"] == COHORT_PROGRAMME
    evidence = env.gemini.last_evidence
    assert evidence, "Approved evidence must reach answer generation."
    assert {chunk["regulation_id"] for chunk in evidence} == {regulation_id}
    assert APPROVED_ATTENDANCE_QUOTE in evidence[0]["chunk_text"]

    # The real Gemini service built the prompt and called the (fake) model once.
    assert len(env.gemini.model_calls) == 1
    assert env.gemini.model_calls[0]["model"] == FAKE_MODEL
    assert env.gemini.client_api_keys == [FAKE_API_KEY]
    prompt = env.gemini.last_prompt
    assert f"admission_batch: {COHORT_BATCH}" in prompt
    assert f"programme: {COHORT_PROGRAMME}" in prompt
    assert ATTENDANCE_QUESTION in prompt
    assert APPROVED_ATTENDANCE_QUOTE in prompt
    assert f"chunk_id: {citation['chunk_id']}" in prompt


# --------------------------------------------------------------------------- #
# 11. Pending and rejected regulations cannot support answers
# --------------------------------------------------------------------------- #


def test_pending_and_rejected_regulations_never_reach_answer_generation(env: E2EEnv) -> None:
    approved_id = _ingest_approved_regulation(env)
    pending_id = _ingest(
        env,
        filename="draft_regulations.pdf",
        pages=PENDING_PAGES,
        document_name="Draft Attendance Amendment",
        regulation_version="R2024-draft",
    )["regulation_id"]
    rejected_id = _ingest(
        env,
        filename="withdrawn_regulations.pdf",
        pages=REJECTED_PAGES,
        document_name="Withdrawn Attendance Amendment",
        regulation_version="R2024-withdrawn",
    )["regulation_id"]
    _set_verification(env, rejected_id, "rejected")

    assert _cohort_regulation_ids(env, COHORT_BATCH, COHORT_PROGRAMME) == [approved_id]

    env.gemini.responder = _answered_citing(APPROVED_ATTENDANCE_QUOTE)
    body = _ask(env)

    assert body["status"] == "answered"
    evidence_ids = {chunk["regulation_id"] for chunk in env.gemini.last_evidence}
    assert evidence_ids == {approved_id}
    assert pending_id not in evidence_ids and rejected_id not in evidence_ids
    assert {result["regulation_id"] for result in body["retrieval"]["results"]} == {approved_id}
    assert {citation["document_name"] for citation in body["citations"]} == {"R2024 B.Tech Regulations"}

    prompt = env.gemini.last_prompt
    assert PENDING_UNIQUE_TEXT not in prompt
    assert REJECTED_UNIQUE_TEXT not in prompt


def test_cohort_with_only_pending_and_rejected_regulations_gets_no_answer(env: E2EEnv) -> None:
    _ingest(
        env,
        filename="draft_regulations.pdf",
        pages=PENDING_PAGES,
        document_name="Draft Attendance Amendment",
        regulation_version="R2024-draft",
    )
    rejected_id = _ingest(
        env,
        filename="withdrawn_regulations.pdf",
        pages=REJECTED_PAGES,
        document_name="Withdrawn Attendance Amendment",
        regulation_version="R2024-withdrawn",
    )["regulation_id"]
    _set_verification(env, rejected_id, "rejected")

    body = _ask(env)

    _assert_safe_insufficient(body)
    assert body["retrieval"]["results"] == []
    assert env.gemini.generation_calls == []
    assert env.gemini.model_calls == []


def test_rejecting_a_previously_approved_regulation_withdraws_its_evidence(env: E2EEnv) -> None:
    regulation_id = _ingest_approved_regulation(env)
    env.gemini.responder = _answered_citing(APPROVED_ATTENDANCE_QUOTE)

    assert _ask(env)["status"] == "answered"
    assert len(env.gemini.model_calls) == 1

    _set_verification(env, regulation_id, "rejected")

    assert _cohort_regulation_ids(env, COHORT_BATCH, COHORT_PROGRAMME) == []
    body = _ask(env)
    _assert_safe_insufficient(body)
    assert len(env.gemini.model_calls) == 1, "Gemini must not be called after the regulation is rejected."


# --------------------------------------------------------------------------- #
# 12. Insufficient evidence produces a safe response
# --------------------------------------------------------------------------- #


def test_cohort_without_any_regulation_gets_safe_insufficient_response(env: E2EEnv) -> None:
    body = _ask(env, batch="2030", programme="B.Arch")

    _assert_safe_insufficient(body)
    assert body["retrieval"]["status"] == "no_evidence"
    assert body["validation_issues"] == []
    assert env.gemini.generation_calls == []
    assert env.gemini.model_calls == []


def test_model_reported_insufficient_evidence_is_returned_without_citations(env: E2EEnv) -> None:
    _ingest_approved_regulation(env)
    # Default responder: the model says the evidence does not answer the question.

    body = _ask(env, question="What is the hostel fee for the 2024 batch?")

    assert len(env.gemini.model_calls) == 1
    _assert_safe_insufficient(body)
    assert body["answer"]["answer"] == "The supplied evidence does not answer this question."


@pytest.mark.parametrize(
    "responder",
    [
        pytest.param(lambda _p, _e: "Sure! Attendance is 75 percent.", id="non_json_output"),
        pytest.param(lambda _p, _e: json.dumps({"answer": "x", "status": "definitely"}), id="invalid_status"),
        pytest.param(lambda _p, _e: json.dumps({"status": "answered", "citations": []}), id="missing_answer"),
    ],
)
def test_malformed_model_output_produces_safe_response(env: E2EEnv, responder: Responder) -> None:
    _ingest_approved_regulation(env)
    env.gemini.responder = responder

    body = _ask(env)

    assert len(env.gemini.model_calls) == 1
    _assert_safe_insufficient(body)


def test_gemini_service_failure_produces_safe_response(env: E2EEnv) -> None:
    _ingest_approved_regulation(env)

    def failing_responder(_prompt: str, _evidence: Sequence[Mapping[str, Any]]) -> str:
        raise ConnectionError("simulated network outage")

    env.gemini.responder = failing_responder

    body = _ask(env)

    assert len(env.gemini.model_calls) == 1
    _assert_safe_insufficient(body)
    assert "simulated network outage" not in json.dumps(body)


def test_answered_status_without_citations_is_downgraded(env: E2EEnv) -> None:
    _ingest_approved_regulation(env)
    env.gemini.responder = lambda _p, _e: json.dumps(
        {"answer": "Attendance must be 75 percent.", "status": "answered", "citations": []}
    )

    body = _ask(env)

    _assert_safe_insufficient(body)


# --------------------------------------------------------------------------- #
# 13. Fabricated citations cannot survive citation validation
# --------------------------------------------------------------------------- #


def test_fabricated_chunk_id_in_model_output_is_rejected(env: E2EEnv) -> None:
    _ingest_approved_regulation(env)
    env.gemini.responder = lambda _p, _e: json.dumps(
        {
            "answer": "Students need only 10 percent attendance.",
            "status": "answered",
            "citations": [
                {
                    "document_name": "R2024 B.Tech Regulations",
                    "regulation_version": "R2024",
                    "page_number": 42,
                    "chunk_id": "999-p42-c7",
                    "relevant_supporting_text": FABRICATED_QUOTE,
                }
            ],
            "limitations": None,
        }
    )

    body = _ask(env)

    _assert_safe_insufficient(body)
    assert "999-p42-c7" in body["answer"]["limitations"]
    assert "10 percent" not in body["answer"]["answer"]


def test_fabricated_quote_on_real_chunk_never_reaches_the_response(env: E2EEnv) -> None:
    """A real chunk_id with an invented quote and metadata is never echoed back.

    The Gemini service replaces unmatched supporting text with an excerpt from
    the cited evidence and restores all metadata from the evidence record.
    """
    _ingest_approved_regulation(env)

    def responder(_prompt: str, evidence: Sequence[Mapping[str, Any]]) -> str:
        chunk = _chunk_containing(evidence, APPROVED_ATTENDANCE_QUOTE)
        return json.dumps(
            {
                "answer": "Students must maintain a minimum of 75 percent attendance in each course.",
                "status": "answered",
                "citations": [
                    {
                        "document_name": "Imaginary Regulation Handbook",
                        "regulation_version": "R1999",
                        "page_number": 404,
                        "chunk_id": chunk["chunk_id"],
                        "relevant_supporting_text": FABRICATED_QUOTE,
                    }
                ],
                "limitations": None,
            }
        )

    env.gemini.responder = responder

    body = _ask(env)

    serialized = json.dumps(body["citations"])
    assert FABRICATED_QUOTE not in serialized
    assert "Imaginary Regulation Handbook" not in serialized
    assert "R1999" not in serialized
    for citation in body["citations"]:
        assert citation["document_name"] == "R2024 B.Tech Regulations"
        assert citation["regulation_version"] == "R2024"
        assert citation["page_number"] == 1
        evidence_chunk = _chunk_containing(env.gemini.last_evidence, APPROVED_ATTENDANCE_QUOTE)
        assert citation["relevant_supporting_text"] in evidence_chunk["chunk_text"]


def _override_answer(env: E2EEnv, build: Callable[[list[dict[str, Any]]], GroundedAnswer]) -> None:
    """Bypass the Gemini service so the final citation validator is tested directly."""

    def override(**kwargs: Any) -> GroundedAnswer:
        return build([dict(chunk) for chunk in kwargs.get("evidence_chunks") or []])

    env.gemini.answer_override = override


def test_final_validator_rejects_citation_to_unknown_chunk(env: E2EEnv) -> None:
    _ingest_approved_regulation(env)
    _override_answer(
        env,
        lambda _evidence: GroundedAnswer(
            answer="Students need only 10 percent attendance.",
            status="answered",
            citations=[
                GroundedCitation(
                    document_name="R2024 B.Tech Regulations",
                    regulation_version="R2024",
                    page_number=1,
                    chunk_id="does-not-exist",
                    relevant_supporting_text=FABRICATED_QUOTE,
                )
            ],
        ),
    )

    body = _ask(env)

    _assert_safe_insufficient(body)
    assert any("unknown chunk_id 'does-not-exist'" in issue for issue in body["validation_issues"])
    assert "10 percent" not in body["answer"]["answer"]


def test_final_validator_rejects_fabricated_supporting_text(env: E2EEnv) -> None:
    _ingest_approved_regulation(env)

    def build(evidence: list[dict[str, Any]]) -> GroundedAnswer:
        chunk = _chunk_containing(evidence, APPROVED_ATTENDANCE_QUOTE)
        return GroundedAnswer(
            answer="Students need only 10 percent attendance.",
            status="answered",
            citations=[
                GroundedCitation(
                    document_name=chunk["document_name"],
                    regulation_version=chunk["regulation_version"],
                    page_number=chunk["page_number"],
                    chunk_id=chunk["chunk_id"],
                    relevant_supporting_text=FABRICATED_QUOTE,
                )
            ],
        )

    _override_answer(env, build)

    body = _ask(env)

    _assert_safe_insufficient(body)
    assert any("supporting text could not be matched" in issue for issue in body["validation_issues"])
    assert FABRICATED_QUOTE not in json.dumps(body["citations"])


def test_final_validator_restores_fabricated_metadata_from_evidence(env: E2EEnv) -> None:
    _ingest_approved_regulation(env)

    def build(evidence: list[dict[str, Any]]) -> GroundedAnswer:
        chunk = _chunk_containing(evidence, APPROVED_ATTENDANCE_QUOTE)
        return GroundedAnswer(
            answer="Students must maintain a minimum of 75 percent attendance in each course.",
            status="answered",
            citations=[
                GroundedCitation(
                    document_name="Imaginary Regulation Handbook",
                    regulation_version="R1999",
                    page_number=404,
                    chunk_id=chunk["chunk_id"],
                    relevant_supporting_text=APPROVED_ATTENDANCE_QUOTE,
                )
            ],
        )

    _override_answer(env, build)

    body = _ask(env)

    assert body["status"] == "answered"
    assert len(body["citations"]) == 1
    citation = body["citations"][0]
    assert citation["document_name"] == "R2024 B.Tech Regulations"
    assert citation["regulation_version"] == "R2024"
    assert citation["page_number"] == 1


def test_final_validator_keeps_valid_citation_and_drops_fabricated_ones(env: E2EEnv) -> None:
    _ingest_approved_regulation(env)

    def build(evidence: list[dict[str, Any]]) -> GroundedAnswer:
        chunk = _chunk_containing(evidence, APPROVED_ATTENDANCE_QUOTE)
        valid = GroundedCitation(
            document_name=chunk["document_name"],
            regulation_version=chunk["regulation_version"],
            page_number=chunk["page_number"],
            chunk_id=chunk["chunk_id"],
            relevant_supporting_text=APPROVED_ATTENDANCE_QUOTE,
        )
        return GroundedAnswer(
            answer="Students must maintain a minimum of 75 percent attendance in each course.",
            status="answered",
            citations=[
                valid,
                GroundedCitation(chunk_id="ghost-chunk", relevant_supporting_text=FABRICATED_QUOTE),
                valid.model_copy(update={"relevant_supporting_text": FABRICATED_QUOTE}),
                valid,
            ],
        )

    _override_answer(env, build)

    body = _ask(env)

    assert body["status"] == "answered"
    assert len(body["citations"]) == 1
    assert body["citations"][0]["relevant_supporting_text"] == APPROVED_ATTENDANCE_QUOTE
    assert FABRICATED_QUOTE not in json.dumps(body["citations"])
    issues = " ".join(body["validation_issues"])
    assert "unknown chunk_id 'ghost-chunk'" in issues
    assert "Removed duplicate citation" in issues
    assert body["answer"]["limitations"]


# --------------------------------------------------------------------------- #
# API documentation remains available
# --------------------------------------------------------------------------- #


def test_openapi_schema_and_docs_cover_end_to_end_routes(env: E2EEnv) -> None:
    docs = env.client.get("/docs")
    assert docs.status_code == 200
    assert "swagger" in docs.text.lower()

    schema_response = env.client.get("/openapi.json")
    assert schema_response.status_code == 200
    paths = schema_response.json()["paths"]
    assert "post" in paths[f"{API}/regulations/ingest"]
    assert "patch" in paths[f"{API}/regulations/{{regulation_id}}/verification"]
    assert "get" in paths[f"{API}/regulations/{{regulation_id}}/pages"]
    assert "get" in paths[f"{API}/cohorts/{{admission_batch}}/{{programme}}/regulations"]
    assert "post" in paths[f"{API}/query/ask"]
